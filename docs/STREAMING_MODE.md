# Streaming Mode - DirectCDPlayer

## Visão Geral

O modo streaming (level 0) permite reprodução direta do CD sem extração para RAM, utilizando o mpv como backend de áudio. Este modo é ideal para situações onde a RAM é limitada ou quando se deseja iniciar a reprodução imediatamente.

## Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                        CDPlayerController                        │
│                                                                  │
│  is_direct_mode = True                                          │
│  direct_player = DirectCDPlayer(...)                            │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                     DirectCDPlayer                          │ │
│  │                                                              │ │
│  │  ┌──────────────┐    ┌─────────────┐    ┌───────────────┐  │ │
│  │  │  mpv process │◄───│  IPC Socket │◄───│ _send_ipc()   │  │ │
│  │  │  (cdda://)   │    │  (Unix)     │    │ _get_property │  │ │
│  │  └──────────────┘    └─────────────┘    └───────────────┘  │ │
│  │         │                                                    │ │
│  │         ▼                                                    │ │
│  │  ┌──────────────┐                                           │ │
│  │  │ ALSA Device  │                                           │ │
│  │  │ (hw:X,Y)     │                                           │ │
│  │  └──────────────┘                                           │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Classe DirectCDPlayer

### Localização
`src/cd_direct_player.py`

### Dependências
- `mpv` - media player (instalado no sistema)
- `config` - configurações do redram

---

## Atributos

| Atributo | Tipo | Descrição |
|----------|------|-----------|
| `cd_device` | str | Dispositivo CD (ex: `/dev/sr0`) |
| `alsa_device` | str | Dispositivo ALSA (ex: `hw:1,0`) |
| `tracks` | List[CDTrack] | Lista de faixas do CD |
| `current_track` | int | Faixa atual (1-indexed) |
| `state` | str | Estado: `'stopped'`, `'playing'`, `'paused'` |
| `on_track_end` | Callable | Callback quando faixa termina |

### Atributos Internos

| Atributo | Tipo | Descrição |
|----------|------|-----------|
| `_process` | subprocess.Popen | Processo mpv |
| `_ipc_socket` | str | Caminho do socket IPC Unix |
| `_monitor_thread` | threading.Thread | Thread de monitoramento |
| `_stop_event` | threading.Event | Sinal para parar thread |
| `_pause_time` | float | Posição ao pausar |
| `_playback_started` | bool | True quando áudio realmente iniciou |

---

## Métodos Públicos

### `__init__(device: str = None, tracks: List = None)`
Inicializa o player.

**Parâmetros:**
- `device`: Dispositivo ALSA (opcional, usa config.ALSA_DEVICE)
- `tracks`: Lista de CDTrack (obtida do ripper.read_toc())

---

### `play_track(track_num: int) -> bool`
Inicia reprodução de uma faixa específica.

**Parâmetros:**
- `track_num`: Número da faixa (1-indexed)

**Retorno:** `True` se sucesso

**Fluxo:**
1. Para thread de monitoramento anterior
2. Garante que mpv está rodando (`_ensure_mpv`)
3. Se CD já carregado no mpv, apenas muda chapter
4. Caso contrário, carrega `cdda://` e define chapter
5. Inicia thread de monitoramento

---

### `pause()`
Pausa a reprodução.

**Comportamento:**
- Salva posição atual em `_pause_time`
- Envia comando pause ao mpv
- Muda state para `'paused'`

---

### `resume()`
Retoma reprodução pausada.

**Comportamento:**
- Envia comando unpause ao mpv
- Muda state para `'playing'`

---

### `stop()`
Para a reprodução.

**Comportamento:**
- Para thread de monitoramento
- Envia comando stop ao mpv
- Reseta `_pause_time` e `_playback_started`
- Muda state para `'stopped'`

---

### `next_track()`
Avança para próxima faixa.

**Comportamento:**
- Se não for última faixa, chama `play_track(current + 1)`

---

### `prev_track()`
Volta para faixa anterior.

**Comportamento:**
- Se não for primeira faixa, chama `play_track(current - 1)`

---

### `get_state() -> str`
Retorna estado atual: `'stopped'`, `'playing'`, `'paused'`

---

### `get_current_track() -> int`
Retorna número da faixa atual (1-indexed).

---

### `get_position() -> float`
Retorna posição atual na faixa em segundos.

**Comportamento:**
- Se `_playback_started` é False: retorna `0.0`
- Se playing: calcula `time-pos - chapter_start`
- Se paused: retorna `_pause_time`
- Se stopped: retorna `0.0`

**Importante:** Retorna `0.0` durante transição de faixa até o áudio realmente iniciar.

---

### `get_duration() -> float`
Retorna duração da faixa atual em segundos.

**Fonte:** `tracks[current_track - 1].duration_seconds`

---

### `cleanup()`
Encerra o player e libera recursos.

**Fluxo:**
1. Para thread de monitoramento
2. Envia comando `quit` ao mpv
3. Aguarda processo terminar (com timeout)
4. Remove socket IPC

---

## Métodos Internos

### `_ensure_mpv() -> bool`
Garante que processo mpv está rodando.

**Parâmetros mpv:**
```
--idle=yes                    # Mantém rodando sem arquivo
--no-video                    # Sem saída de vídeo
--ao=alsa                     # Output ALSA
--audio-device=alsa/hw:X,Y    # Dispositivo específico
--audio-pitch-correction=no   # Sem correção de pitch
--audio-normalize-downmix=no  # Sem normalização
--replaygain=no               # Sem ReplayGain
--volume=100                  # Volume máximo
--volume-max=100              # Limite de volume
--af=                         # Sem filtros de áudio
--audio-swresample-o=         # Sem opções de resample
--no-terminal                 # Sem output de terminal
--really-quiet                # Silencioso
--input-ipc-server=SOCKET     # Socket IPC
```

---

### `_send_ipc(command: list) -> dict`
Envia comando via socket Unix para mpv.

**Protocolo:** JSON-IPC do mpv

**Exemplo:**
```python
_send_ipc(["set_property", "pause", True])
# Envia: {"command": ["set_property", "pause", true]}\n
# Recebe: {"error": "success"}\n
```

---

### `_get_property(prop: str) -> Any`
Obtém propriedade do mpv.

**Propriedades utilizadas:**
| Propriedade | Tipo | Descrição |
|-------------|------|-----------|
| `chapter` | int | Chapter atual (0-indexed) |
| `time-pos` | float | Posição absoluta no disco |
| `eof-reached` | bool | True se chegou ao fim |
| `core-idle` | bool | True se mpv está ocioso |
| `path` | str | Arquivo/URL atual |

**Nota:** A propriedade `chapter-list` do mpv retorna lista vazia para CDs, então calculamos os tempos de início das faixas usando as durações do TOC.

---

### `_get_chapter_start(track_num: int) -> float`
Calcula o tempo de início de uma faixa baseado nas durações do TOC.

**Parâmetros:**
- `track_num`: Número da faixa (1-indexed)

**Retorno:** Tempo em segundos desde o início do disco

**Cálculo:**
```python
start = sum(tracks[i].duration_seconds for i in range(track_num - 1))
```

---

### `_monitor_playback()`
Thread que monitora reprodução.

**Fase 1 - Aguarda início do áudio:**
```
chapter_start = _get_chapter_start(current_track)  # Calculado do TOC

Loop (timeout 20s):
  - Obtém time-pos do mpv
  - Calcula track_pos = time-pos - chapter_start
  - Se track_pos > 0.1: _playback_started = True, break
```

**Fase 2 - Monitora fim da faixa:**
```
Loop:
  - Se chapter mudou: faixa terminou (chapter change)
  - Se eof-reached: faixa terminou (EOF)
  - Chama on_track_end em nova thread
```

---

## Integração com CDPlayerController

### Ativação do Modo Streaming

```python
# Em cd_controller.py
def load(self, extraction_level=0):
    if extraction_level == 0:
        return self._load_streaming_mode()
```

### Fluxo de Carregamento

```python
def _load_streaming_mode(self):
    1. self.scan()                    # Lê TOC do CD
    2. tracks = self.get_scanned_tracks()
    3. self.direct_player = DirectCDPlayer(tracks=tracks)
    4. self.direct_player.on_track_end = self._on_streaming_track_end
    5. self.is_direct_mode = True
    6. self.direct_player.play_track(1)  # Inicia reprodução
```

### Delegação de Comandos

Quando `is_direct_mode = True`, o controller delega para `direct_player`:

| Método Controller | Método DirectCDPlayer |
|-------------------|----------------------|
| `play()` | `resume()` ou `play_track()` |
| `pause()` | `pause()` |
| `stop()` | `stop()` |
| `next()` | `next_track()` |
| `prev()` | `prev_track()` |
| `get_position()` | `get_position()` |
| `get_duration()` | `get_duration()` |
| `get_state()` | `get_state()` |
| `get_current_track_num()` | `get_current_track()` |
| `get_total_tracks()` | `len(tracks)` |

### Callback de Fim de Faixa

```python
def _on_streaming_track_end(self):
    # Repeat track
    if repeat_mode == TRACK:
        direct_player.play_track(current)

    # Próxima faixa
    elif current < total:
        direct_player.play_track(current + 1)
        on_track_change(next_track, total)

    # Repeat all
    elif repeat_mode == ALL:
        direct_player.play_track(1)
        on_track_change(1, total)

    # Fim do disco
    else:
        on_status_change("disc_end")
```

---

## Conceitos Importantes

### Chapters vs Tracks

O mpv trata cada faixa do CD como um "chapter":
- Track 1 = Chapter 0
- Track 2 = Chapter 1
- Track N = Chapter N-1

### Posição Absoluta vs Relativa

- `time-pos`: Posição absoluta desde o início do CD
- `chapter_start`: Tempo de início do chapter na chapter-list
- `track_pos = time-pos - chapter_start`: Posição relativa à faixa

### Flag _playback_started

Controla quando o áudio realmente começou:
- `False` durante transição de faixa
- `True` quando `track_pos > 0.1s`
- Garante que `get_position()` retorne `0.0` durante transição

---

## Diferenças: RAM Mode vs Streaming Mode

| Aspecto | RAM Mode | Streaming Mode |
|---------|----------|----------------|
| Extração | Completa para /dev/shm | Nenhuma |
| Início | Após extração completa | Imediato |
| Uso de RAM | ~700MB por CD | Mínimo |
| Backend | ALSA direto | mpv |
| Gapless | Nativo | Via chapters |
| Seek | Instantâneo | Depende do drive |

---

## Troubleshooting

### Tempo fica em 00:00
- Verificar se `_playback_started` está sendo setado
- Verificar se `chapter-list` está disponível no mpv
- Log: `DirectCDPlayer: audio started for track X`

### Faixa não avança automaticamente
- Verificar callback `on_track_end`
- Verificar se `_monitor_thread` está rodando
- Log: `DirectCDPlayer: track X ended`

### mpv não inicia
- Verificar se mpv está instalado: `which mpv`
- Verificar socket IPC: `ls /tmp/mpv_*.sock`
- Log: `DirectCDPlayer: failed to start mpv`
