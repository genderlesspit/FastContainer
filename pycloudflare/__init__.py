import asyncio
from typing import List

from gowershell import Response
from loguru import logger as log
from pywershell import Pywersl

REPR = "[CloudflaredCLI]"
BASE_CMD = "cloudflared"
VERSION = None
PYWERSL: Pywersl


async def install() -> list:
    log.warning(f"{REPR}: Installing cloudflared via Cloudflare's official repo...")
    cmds = [
        "'curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared'",
        "'chmod +x /usr/local/bin/cloudflared'",
        "'cloudflared --version'"
    ]
    out = await PYWERSL.run(cmds)
    return out[2].output


async def version():
    out = await PYWERSL.run("'cloudflared --version'")  # ignore code 127
    if out.error and "127" in out.error:
        return await install()
    else:
        return out.output


async def main():
    global PYWERSL
    PYWERSL = await Pywersl()
    ver = await version()
    global VERSION
    VERSION = ver
    log.debug(f"{REPR}: Running {VERSION}")


asyncio.run(main())


async def cloudflared(cmd: list | str = None, headless=False) -> Response | List[Response]:
    if cmd is None: cmd = []
    if cmd is str: cmd = [cmd]

    out = await PYWERSL.run(cmd, headless=headless)
    return out


def sync_cloudflared(cmd: list | str = None, headless=False) -> Response | List[Response]:
    if cmd is None: cmd = []
    if cmd is str: cmd = [cmd]

    out = asyncio.run(cloudflared(cmd, headless))
    return out

from .cloudflare_api import Cloudflare

# VERSION =
#     # self.login()
#     # except Exception: raise RuntimeError(f"{self}: Cloudflared container failed to start")
#     # log.success(f"{self}: Session initialized!")
#     return result
#
#
#
# def login(self):
#     output = Pywersl.run(["cloudflared", "tunnel", "list"], ignore_codes=[1])
#     if "ERR Cannot determine default origin" in output:
#         self.run(["tunnel", "login"], headless=False)
#         log.error("Please create a valid user login session with Cloudflared CLI... Ending this session...")
#         sys.exit()
#
#
#
#
# from cloudflared_cli import CloudflaredCLI
#
