# HIKMICRO USB thermal video on Linux

Capture color thermal video at **256×192 and 25 fps** from the HIKMICRO camera with USB ID **`2bdf:0102`**. The Python script reads the camera through PyUSB and supplies raw NV12 frames to stock FFmpeg. It works with the factory camera firmware and the standard Linux kernel.

## The problem

On the tested camera, Windows DirectShow could capture a color thermal image in NV12 at 256×192. Linux listed the same mode in V4L2, but requesting it returned `Input/output error` before FFmpeg received a frame.

Two things stood out in the USB negotiation.

| Observation | Result |
| --- | --- |
| The camera's UVC descriptors | Format index **2**, frame index **2** advertises NV12 at 256×192, 25 fps. Format index **1** advertises YUYV. |
| Linux sends `GET_MIN` for the UVC Video Probe control | The camera stalls the request. Linux reports USB error `-32` (`EPIPE`) and mode selection fails. |
| A direct `SET_CUR` / `GET_CUR` probe requests NV12 | The reply reports format index **1**, frame index **2**. Committing that reply still produces complete **73,728-byte** frames that render correctly as 256×192 NV12. |

These observations came from one camera with this USB ID. The driver's probe sequence is visible in the [Linux 6.6 UVC source](https://github.com/torvalds/linux/blob/v6.6/drivers/media/usb/uvc/uvc_video.c).

## The workaround

[`hikmicro_nv12.py`](hikmicro_nv12.py) temporarily detaches the Linux UVC driver from the camera and claims its USB streaming interface. It requests the advertised NV12 mode, reads the probe reply, and commits that reply as received. It reassembles the USB bulk payloads and sends valid 73,728-byte frames to stdout.

FFmpeg reads stdin as raw NV12 with the dimensions and frame rate supplied explicitly. It can then display, record, or encode the video using its regular inputs and encoders. [FFmpeg rawvideo documentation](https://ffmpeg.org/ffmpeg-formats.html#rawvideo)

## Quick start

Install the dependencies on Debian, Ubuntu, or Raspberry Pi OS.

```sh
sudo apt install python3-usb ffmpeg
```

From this directory, use Bash to record 125 frames (five seconds at 25 fps).

```bash
set -o pipefail
sudo /usr/bin/python3 hikmicro_nv12.py --frames 125 |
  ffmpeg -hide_banner -f rawvideo -pixel_format nv12 -video_size 256x192 \
    -framerate 25 -i pipe:0 -c:v libx264 -pix_fmt yuv420p -n capture.mp4
```

To preview live video, omit `--frames` and use `ffplay`.

```bash
sudo /usr/bin/python3 hikmicro_nv12.py |
  ffplay -f rawvideo -pixel_format nv12 -video_size 256x192 -framerate 25 -i pipe:0
```

The examples use `sudo` so PyUSB can claim the interface and detach its kernel driver. Close other programs using the camera before starting the script. The script releases the camera and reattaches its previous driver on normal exit.

## What was verified

- On **Raspberry Pi 4** running Raspberry Pi OS Bookworm (64-bit, Linux 6.6), the script and the stock FFmpeg recorded all 125 frames, and the resulting MP4 showed a color thermal image.
- On **Ubuntu 24.04 under WSL 2**, the same script recorded 125 frames with the camera attached using USB/IP.

The output is color preview video over stdout. Applications that expect a V4L2 device or per-pixel temperature readings need a separate solution. Verification covers the `2bdf:0102` unit described above.
