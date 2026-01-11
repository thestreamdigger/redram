import subprocess
import os
import re
import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Callable
import config

logger = logging.getLogger(__name__)


@dataclass
class CDTrack:
    number: int
    start_sector: int
    end_sector: int
    length_sectors: int
    duration_seconds: float
    filename: str = ""
    title: str = ""
    artist: str = ""

    def __str__(self):
        mins = int(self.duration_seconds // 60)
        secs = int(self.duration_seconds % 60)
        if self.title:
            return f"Track {self.number:02d} - {self.title} ({mins:02d}:{secs:02d})"
        return f"Track {self.number:02d} - {mins:02d}:{secs:02d}"


class CDRipper:

    def __init__(self, device: str = None, ram_path: str = None):
        self.device = device or config.CD_DEVICE
        self.ram_path = ram_path or config.RAM_PATH
        self.tracks: List[CDTrack] = []
        self.disc_id: Optional[str] = None
        self.disc_title: str = ""
        self.disc_artist: str = ""
        self.extraction_level: int = config.DEFAULT_EXTRACTION_LEVEL

        logger.debug(f"RIPPER: initialized device={self.device}, ram_path={self.ram_path}")

    def detect_cd(self, max_retries: int = 2) -> bool:
        logger.debug(f"RIPPER: detecting CD on {self.device}")

        for attempt in range(max_retries):
            try:
                start_time = time.time()
                result = subprocess.run(
                    [config.CDPARANOIA_PATH, '-d', self.device, '-Q'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                elapsed = (time.time() - start_time) * 1000

                if 'TOTAL' in result.stderr or 'TOTAL' in result.stdout:
                    logger.info(f"RIPPER: CD detected in {elapsed:.0f}ms")
                    return True

                if attempt < max_retries - 1:
                    logger.debug(f"RIPPER: no CD found, retrying...")
                    time.sleep(0.5)

            except subprocess.TimeoutExpired:
                logger.debug(f"RIPPER: timeout detecting CD")
                if attempt < max_retries - 1:
                    time.sleep(0.3)
            except Exception as e:
                logger.debug(f"RIPPER: detect error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.3)

        logger.warning(f"RIPPER: no CD detected")
        return False

    def read_toc(self) -> List[CDTrack]:
        logger.debug("RIPPER: reading TOC...")
        start_time = time.time()

        try:
            result = subprocess.run(
                [config.CDPARANOIA_PATH, '-d', self.device, '-Q'],
                capture_output=True,
                text=True,
                timeout=10
            )

            output = result.stderr + result.stdout
            tracks = []

            for line in output.split('\n'):
                match = re.search(r'^\s*(\d+)\.\s+(\d+)\s+\[(\d+):(\d+)\.(\d+)\]', line)
                if match:
                    track_num = int(match.group(1))
                    start_sector = int(match.group(2))
                    minutes = int(match.group(3))
                    seconds = int(match.group(4))
                    frames = int(match.group(5))

                    duration = minutes * 60 + seconds + frames / 75.0

                    tracks.append({
                        'number': track_num,
                        'start_sector': start_sector,
                        'duration': duration
                    })

            self.tracks = []
            for i, track_info in enumerate(tracks):
                if i < len(tracks) - 1:
                    end_sector = tracks[i + 1]['start_sector'] - 1
                else:
                    total_match = re.search(r'TOTAL\s+(\d+)', output)
                    if total_match:
                        end_sector = int(total_match.group(1))
                    else:
                        end_sector = track_info['start_sector'] + int(track_info['duration'] * 75)

                length = end_sector - track_info['start_sector'] + 1

                track = CDTrack(
                    number=track_info['number'],
                    start_sector=track_info['start_sector'],
                    end_sector=end_sector,
                    length_sectors=length,
                    duration_seconds=track_info['duration'],
                    filename=f"track{track_info['number']:02d}.wav"
                )
                self.tracks.append(track)

            elapsed = (time.time() - start_time) * 1000
            total_duration = sum(t.duration_seconds for t in self.tracks)
            logger.info(f"RIPPER: TOC read in {elapsed:.0f}ms - {len(self.tracks)} tracks, {total_duration:.0f}s total")

            for track in self.tracks:
                logger.debug(f"RIPPER: track {track.number:02d} - {track.duration_seconds:.1f}s ({track.length_sectors} sectors)")

            return self.tracks

        except Exception as e:
            logger.error(f"RIPPER: failed to read TOC: {e}")
            return []

    def read_cdtext(self) -> bool:
        if not self.tracks:
            return False

        try:
            result = subprocess.run(
                ['cd-info', '--no-header', '-C', self.device],
                capture_output=True,
                text=True,
                timeout=5
            )
            output = result.stdout + result.stderr

            disc_title = ""
            disc_artist = ""
            track_titles = {}
            current_track = None

            for line in output.split('\n'):
                line = line.strip()

                track_match = re.match(r'CD-TEXT for Track\s+(\d+):', line)
                if track_match:
                    current_track = int(track_match.group(1))
                    continue

                if line.startswith('CD-TEXT for Disc:'):
                    current_track = None
                    continue

                if line.startswith('TITLE:'):
                    title = line.split(':', 1)[1].strip().strip("'\"")
                    if current_track is not None:
                        track_titles[current_track] = title
                    elif not disc_title:
                        disc_title = title

                elif line.startswith('PERFORMER:'):
                    artist = line.split(':', 1)[1].strip().strip("'\"")
                    if not disc_artist:
                        disc_artist = artist

            if disc_title or disc_artist or track_titles:
                self.disc_title = disc_title
                self.disc_artist = disc_artist
                for track in self.tracks:
                    if track.number in track_titles:
                        track.title = track_titles[track.number]
                    if disc_artist:
                        track.artist = disc_artist
                logger.info(f"RIPPER: CD-Text found - {disc_artist or 'Unknown'} / {disc_title or 'Unknown'}")
                return True

        except FileNotFoundError:
            logger.debug("RIPPER: cd-info not found, CD-Text unavailable")
        except Exception as e:
            logger.debug(f"RIPPER: CD-Text read failed: {e}")

        return False

    def set_extraction_level(self, level: int):
        if level in config.EXTRACTION_LEVELS:
            self.extraction_level = level
            level_info = config.EXTRACTION_LEVELS[level]
            logger.info(f"RIPPER: extraction level={level} ({level_info['name']})")
        else:
            logger.warning(f"RIPPER: invalid level {level}, using default")
            self.extraction_level = config.DEFAULT_EXTRACTION_LEVEL

    def get_extraction_level_info(self) -> dict:
        return config.EXTRACTION_LEVELS.get(self.extraction_level, config.EXTRACTION_LEVELS[1])

    def _rip_track_cdparanoia(self, track: CDTrack, output_file: str, level_info: dict) -> bool:
        cmd = [config.CDPARANOIA_PATH, '-d', self.device]
        cmd.extend(level_info['flags'])

        if hasattr(config, 'CD_READ_OFFSET') and config.CD_READ_OFFSET != 0:
            cmd.extend(['-O', str(config.CD_READ_OFFSET)])

        if config.RIP_SPEED_LIMIT:
            cmd.extend(['-s', config.RIP_SPEED_LIMIT])

        cmd.append(str(track.number))
        cmd.append(output_file)

        logger.debug(f"RIPPER: extracting track {track.number} (cdparanoia) - cmd: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=level_info['timeout']
        )

        if result.returncode != 0:
            logger.error(f"RIPPER: track {track.number} failed: {result.stderr[:200]}")
            return False

        return True

    def rip_to_ram(self, progress_callback: Optional[Callable] = None, max_retries: int = 2) -> bool:
        if not self.tracks:
            logger.error("RIPPER: no tracks to extract. Run read_toc() first")
            return False

        os.makedirs(self.ram_path, exist_ok=True)

        level_info = self.get_extraction_level_info()
        total_duration = sum(t.duration_seconds for t in self.tracks)

        logger.info(f"RIPPER: starting extraction of {len(self.tracks)} tracks ({total_duration:.0f}s) to {self.ram_path}")
        logger.info(f"RIPPER: mode=level {self.extraction_level} ({level_info['name']}), tool=cdparanoia, timeout={level_info['timeout']}s")

        extraction_start = time.time()

        for track in self.tracks:
            output_file = os.path.join(self.ram_path, track.filename)
            success = False

            for attempt in range(max_retries):
                try:
                    track_start = time.time()

                    if progress_callback:
                        status = "extracting" if attempt == 0 else f"retry {attempt}"
                        progress_callback(track.number, len(self.tracks), status)

                    success = self._rip_track_cdparanoia(track, output_file, level_info)

                    if success and os.path.exists(output_file):
                        file_size = os.path.getsize(output_file)
                        track_elapsed = time.time() - track_start
                        speed = track.duration_seconds / track_elapsed if track_elapsed > 0 else 0
                        logger.info(f"RIPPER: track {track.number:02d} extracted in {track_elapsed:.1f}s ({file_size/1024/1024:.1f}MB, {speed:.1f}x)")
                        break

                    logger.warning(f"RIPPER: track {track.number} attempt {attempt+1} failed")

                except subprocess.TimeoutExpired:
                    logger.warning(f"RIPPER: track {track.number} timeout (attempt {attempt+1})")
                except Exception as e:
                    logger.warning(f"RIPPER: track {track.number} error (attempt {attempt+1}): {e}")

                if attempt < max_retries - 1:
                    time.sleep(0.5)

            if not success:
                logger.error(f"RIPPER: track {track.number} failed after {max_retries} attempts")
                return False

        if progress_callback:
            progress_callback(len(self.tracks), len(self.tracks), "complete")

        total_elapsed = time.time() - extraction_start
        total_size = sum(os.path.getsize(os.path.join(self.ram_path, t.filename)) for t in self.tracks)
        avg_speed = total_duration / total_elapsed if total_elapsed > 0 else 0

        logger.info(f"RIPPER: extraction complete in {total_elapsed:.1f}s ({total_size/1024/1024:.0f}MB, avg {avg_speed:.1f}x)")
        return True

    def load_track_data(self, track_num: int) -> Optional[bytes]:
        if track_num < 1 or track_num > len(self.tracks):
            logger.error(f"RIPPER: invalid track number {track_num}")
            return None

        track = self.tracks[track_num - 1]
        filepath = os.path.join(self.ram_path, track.filename)

        if not os.path.exists(filepath):
            logger.error(f"RIPPER: file not found: {filepath}")
            return None

        try:
            start_time = time.time()

            with open(filepath, 'rb') as f:
                f.seek(44)
                pcm_data = f.read()

            elapsed = (time.time() - start_time) * 1000
            logger.debug(f"RIPPER: track {track_num} loaded in {elapsed:.1f}ms - {len(pcm_data)} bytes")
            return pcm_data

        except Exception as e:
            logger.error(f"RIPPER: failed to load track {track_num}: {e}")
            return None

    def get_track_info(self, track_num: int) -> Optional[CDTrack]:
        if track_num < 1 or track_num > len(self.tracks):
            return None
        return self.tracks[track_num - 1]

    def _get_track_filepath(self, track_num: int) -> str:
        if track_num < 1 or track_num > len(self.tracks):
            return ""
        track = self.tracks[track_num - 1]
        return os.path.join(self.ram_path, track.filename)

    def cleanup(self):
        logger.debug("RIPPER: cleanup starting...")
        removed = 0
        try:
            for track in self.tracks:
                filepath = os.path.join(self.ram_path, track.filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                    removed += 1
            logger.info(f"RIPPER: cleanup complete - removed {removed} files")
        except Exception as e:
            logger.error(f"RIPPER: cleanup error: {e}")
