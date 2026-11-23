#!/usr/bin/env python3
"""Stream 256x192 NV12 at 25 fps from the HIK 2bdf:0102 to stdout."""

import argparse
from contextlib import contextmanager
import struct
import sys
import time

import usb.core
import usb.util


WIDTH, HEIGHT = 256, 192
FRAME_BYTES = WIDTH * HEIGHT * 3 // 2
STREAM_INTERFACE = 1
ENDPOINT = 0x81


@contextmanager
def claim_stream(camera):
    detached = []
    claimed = False
    try:
        # Unbinding the UVC control interface generally releases both interfaces.
        for interface in (0, STREAM_INTERFACE):
            if camera.is_kernel_driver_active(interface):
                camera.detach_kernel_driver(interface)
                detached.append(interface)
        usb.util.claim_interface(camera, STREAM_INTERFACE)
        claimed = True
        yield
    finally:
        try:
            if claimed:
                usb.util.release_interface(camera, STREAM_INTERFACE)
        finally:
            try:
                for interface in detached:
                    if not camera.is_kernel_driver_active(interface):
                        camera.attach_kernel_driver(interface)
            finally:
                usb.util.dispose_resources(camera)


def start_nv12(camera):
    # UVC 1.1 VS_PROBE_CONTROL. In the descriptors NV12 is format 2, frame 2.
    probe = bytearray(34)
    struct.pack_into('<HBBI', probe, 0, 1, 2, 2, 400000)
    camera.ctrl_transfer(0x21, 0x01, 0x0100, STREAM_INTERFACE, probe)
    reply = bytes(camera.ctrl_transfer(0xa1, 0x81, 0x0100, STREAM_INTERFACE, 34))
    if len(reply) != 34 or reply[2] not in (1, 2) or reply[3] != 2:
        raise RuntimeError('Unexpected UVC probe response: ' + reply.hex())
    # This firmware reports format 1 for NV12. Commit its reply verbatim.
    camera.ctrl_transfer(0x21, 0x01, 0x0200, STREAM_INTERFACE, reply)
    max_payload = struct.unpack_from('<I', reply, 22)[0]
    if not 2 < max_payload <= 262144:
        raise RuntimeError(f'Unexpected UVC bulk payload size: {max_payload}')
    packet = camera.get_active_configuration()[(STREAM_INTERFACE, 0)][0].wMaxPacketSize
    return ((max_payload + packet - 1) // packet) * packet


def frames(camera, read_size):
    data = bytearray()
    fid = None
    valid = False
    deadline = time.monotonic() + 5
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError('No complete 256x192 NV12 frame received in 5 seconds')
        payload = bytes(camera.read(ENDPOINT, read_size, timeout=2000))
        if not payload:
            continue
        if len(payload) < 2 or not 2 <= payload[0] <= len(payload):
            valid = False
            continue
        flags = payload[1]
        if flags & 1 != fid:
            data.clear()
            fid = flags & 1
            valid = True
        if flags & 0x40 or len(data) + len(payload) - payload[0] > FRAME_BYTES:
            valid = False
        if valid:
            data.extend(payload[payload[0]:])
        if flags & 2:
            if valid and len(data) == FRAME_BYTES:
                yield data
                deadline = time.monotonic() + 5
            data.clear()
            valid = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int, help='stop after this many complete frames')
    args = parser.parse_args()
    if args.frames is not None and args.frames < 1:
        parser.error('--frames must be positive')
    cameras = list(usb.core.find(find_all=True, idVendor=0x2bdf, idProduct=0x0102))
    if len(cameras) != 1:
        raise RuntimeError(f'Expected one HIK 2bdf:0102 camera, found {len(cameras)}')
    camera = cameras[0]
    with claim_stream(camera):
        for count, frame in enumerate(frames(camera, start_nv12(camera)), start=1):
            sys.stdout.buffer.write(frame)
            if count == args.frames:
                break
        sys.stdout.buffer.flush()


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    except (usb.core.USBError, RuntimeError) as exc:
        sys.exit(f'hikmicro: {exc}')
