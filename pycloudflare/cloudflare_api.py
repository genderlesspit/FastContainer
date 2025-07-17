import asyncio
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import toml
from async_property import async_cached_property
from asyncinit import asyncinit
from loguru import logger as log
from singleton_decorator import singleton
from thread_manager import ManagedThread

from api_manager import APIGateway
from pycloudflare import cloudflared, sync_cloudflared

DEFAULT_CONFIG = {
    "info": {
        "hostname": "",
        "service_url": ""
    },
    "tunnel": {
        "name": "",
        "id": "",
        "token": "",
        "meta": ""
    }
}

@dataclass
class Info:
    domain: str
    service_url: str

    @classmethod
    def default(cls):
        return cls(domain="", service_url="")

@dataclass
class Tunnel:
    name: str
    id: str
    token: str
    meta: dict

    @classmethod
    def default(cls):
        return cls(name="", id="", token="", meta={})

@dataclass
class CFG:
    path: Path
    info: Info
    tunnel: Tunnel

    @classmethod
    def from_toml(cls, path: Path):
        info = Info.default()
        tunnel = Tunnel.default()
        items = [path, info, tunnel]
        inst = cls(*items)
        if not inst.path.exists():
            log.warning(f"{inst}: toml for CloudflareAPI config not yet found... Creating...")
            inst.path.touch()
            inst.write()
        else: inst.read()
        return inst

    def write(self):
        if not self.path: raise RuntimeWarning(f"{self}: Could not update CloudflareAPI config! It most likely wasn't initialized from the CloudflareAPI Gateway")
        f = self.path.open("w")
        info = dict(info=self.info.__dict__)
        tunnel = dict(tunnel=self.tunnel.__dict__)
        toml.dump(info, f)
        f.write("\n")
        toml.dump(tunnel, f)

    def read(self):
        if not self.path: raise RuntimeWarning(f"{self}: Could not update CloudflareAPI config! It most likely wasn't initialized from the CloudflareAPI Gateway")
        f = self.path.open("r")
        data = toml.load(f)
        log.debug(f"{self}: Loaded config from .toml:\ndata={data}")
        try:
            self.info = Info(**data["info"])
            self.tunnel = Tunnel(**data["tunnel"])
        except KeyError:
            return self

CFG = CFG.from_toml

@singleton
@asyncinit
class Cloudflare(APIGateway):
    async def __init__(self, toml: Path):
        APIGateway.__init__(self, toml)
        self.cwd = toml.parent
        _, _, _, _ = self.cloudflare_cfg, await self.tunnel, await self.connect_server, await self.dns_record

    def __repr__(self):
        return f"[Cloudflare.Gateway]"

    @cached_property
    def cloudflare_cfg(self) -> CFG:
        path = Path(self.cwd / "cloudflare_api.toml")
        cfg = CFG(path)
        log.debug(cfg)
        return cfg
    
    @cached_property
    def name(self) -> str:
        domain = self.cloudflare_cfg.info.domain
        n = domain.split(".")
        return n[0]

    # noinspection PyTypeChecker
    @async_cached_property
    async def tunnel(self) -> Tunnel:
        # if not self.cloudflare_cfg.tunnel.id or self.cloudflare_cfg.tunnel.token:
        name = f"{self.name}-tunnel"
        out = await self.api_post(
            route="tunnel",
            json={
                "name": f"{name}",
                "config_src": "cloudflare"
            }
        )
        log.debug(out)
        out2 = await self.api_get(
                    route="tunnel",
                    # json={
                    #     "name": f"{name}-tunnel",
                    #     "config_src": "cloudflare"
                    # }
                )
        log.debug(out2)
        #     # if out.status == 409:
        #     #     log.debug(f"{self}: Tunnel for {name} already exists!")
        #     #
        time.sleep(55)
        #     # meta: dict = out.body["result"]
        #     # tunnel = Tunnel(name=name, id=meta["id"], token=meta["token"], meta=meta)
        #     # self.cloudflare_cfg.tunnel = tunnel
        #     # self.cloudflare_cfg.write()
        # # else: return self.cloudflare_cfg.tunnel

    @async_cached_property
    async def connect_server(self):
        ingress_cfg = {
            "config": {
                "ingress": [
                    {
                        "hostname": f"{self.cloudflare_cfg.info.domain}",
                        "service": f"{self.cloudflare_cfg.info.service_url}",
                        "originRequest": {}
                    },
                    {
                        "service": "http_status:404"
                    }
                ]
            }
        }
        out = await self.api_put(
            route="tunnel",
            append=f"/{self.tunnel.id}/configurations",
            json=ingress_cfg,
            force_refresh=False
        )
        return out

    @async_cached_property
    async def dns_record(self):
        # record_name = "phazebreak.work"
        # records = asyncio.run(self.receptionist.get("dns_record", append="?zone_id=$ZONE_ID"))
        # record_id = next(r["id"] for r in records.content["result"] if r["name"] == record_name)
        # asyncio.run(self.receptionist.delete(f"dns_record", append=f"{record_id}"))

        cfg = {
            "type": "CNAME",
            "proxied": True,
            "name": f"{self.cloudflare_cfg.info.domain}",
            "content": f"{self.cloudflare_cfg.tunnel.id}.cfargotunnel.com"
        }
        out = await self.api_post(route="dns_record", json=cfg, force_refresh=False)
        return out

    @ManagedThread
    async def launcher(self):
        # from mileslib_infra import Global
        # glo = Global.get_instance()
        # script = glo.directory / "set_clean_dns.ps1"
        # ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
        #                                     f"-ExecutionPolicy Bypass -File \"{script}\"", None, 1)
        # log.debug(f"{self}: Checking that WSL can see {self.server.url}...")
        # # wsl.run(["curl", "-v", f"{self.server.url}/healthz"], raw=True)
        # log.debug(f"{self}: WSL can reach {self.server.url}/healthz")
        log.debug(f"{self}: Attempting to run tunnel...")
        await cloudflared(f"tunnel run --protocol h2mux --token {self.tunnel.token}", headless=True)
        # out = await self.api_get(route="tunnel", append=f"/{self.tunnel.id}", force_refresh=False)
        # return out

async def debug():
    await Cloudflare(Path(r"C:\Users\cblac\PycharmProjects\FastContainer\test.toml"))

if __name__ == "__main__":
    asyncio.run(debug())
    time.sleep(100)
