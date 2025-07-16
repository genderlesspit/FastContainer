import json
import subprocess
import sys
from functools import cached_property

from async_property import async_cached_property
from loguru import logger as log

from pywershell import pywersl
from singleton_decorator import singleton


@singleton
class CloudflaredCLI:
    def __init__(self):
        _ = self.validate

    def __repr__(self):
        return f"[CloudflaredCLI]"

    @async_cached_property
    async def wsl(self):
        return await pywersl

    @cached_property
    def base_cmd(self) -> list:
        cmd = ["cloudflared"]
        return cmd

    @cached_property
    def validate(self):
        try:
            result = self.wsl.run(["cloudflared", "--version"], ignore_codes=[127])
            if "cloudflared: command not found" in result: self.install()
            self.login()
        except Exception: raise RuntimeError(f"{self}: Cloudflared container failed to start")
        log.success(f"{self}: Session initialized!")
        return result

    def install(self):
        log.warning(f"{self}: Installing cloudflared via Cloudflare's official repo...")
        cmds = [
            "curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared",
            "chmod +x /usr/local/bin/cloudflared",
            "cloudflared --version"
        ]
        self.wsl.run(cmds)
        return

    def login(self):
            output = self.wsl.run(["cloudflared", "tunnel", "list"], ignore_codes=[1])
            if "ERR Cannot determine default origin" in output:
                self.run(["tunnel", "login"], headless=False)
                log.error("Please create a valid user login session with Cloudflared CLI... Ending this session...")
                sys.exit()

    def run(self, cmd: list | str = None, headless=False, expect_json=False, background=False):
        if cmd is None: cmd = []
        if isinstance(cmd, str): cmd = cmd.split()
        if not isinstance(cmd, list): raise TypeError("cmd must be str or list")

        full_cmd = self.base_cmd + cmd
        joined_cmd = " ".join(full_cmd)
        wsl_cmd = self.wsl.base_cmd + [joined_cmd]

        if background:
            log.debug(f"[CloudflaredCLI] Running in background: {' '.join(map(str, wsl_cmd))}")
            return subprocess.Popen(wsl_cmd)

        if headless is False:
            real_cmd = ["cmd.exe", "/c", "start", "cmd", "/k"] + wsl_cmd
            log.debug(f"[CloudflaredCLI] Running in visible shell: {' '.join(map(str, wsl_cmd))}")
            return subprocess.Popen(real_cmd)

        # Default blocking subprocess
        output = self.wsl.run([joined_cmd])
        if expect_json:
            try:
                return json.loads(output)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON from cloudflared: {output[:300]}") from e

        return output

