import threading
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import toml
from async_property import async_cached_property
from loguru import logger as log
from toomanythreads import ManagedThread

from .api_manager import APIGateway
from pycloudflare.api_manager import Response
from pycloudflare import cloudflared

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

    def __repr__(self):
        return "[Cloudflare.CFG]"

    @classmethod
    def from_toml(cls, path: Path):
        info = Info.default()
        tunnel = Tunnel.default()
        items = [path, info, tunnel]
        inst = cls(*items)
        if not inst.path.exists():
            log.warning(f"{inst}: toml for CloudflareAPI config not yet found... Creating...")
            inst.path.touch()
            time.sleep(1.5)
            inst.info.domain = input(f"Please input your Cloudflare domain below:\n")
            inst.write()
        else: inst.read()
        return inst

    def write(self):
        log.debug(f"{self}: Attempting to write to {self.path}")
        f = self.path.open("w")
        info = dict(info=self.info.__dict__)
        tunnel = dict(tunnel=self.tunnel.__dict__)
        toml.dump(info, f)
        f.write("\n")
        toml.dump(tunnel, f)

    def read(self):
        log.debug(f"{self}: Attempting to read {self.path}")
        f = self.path.open("r")
        data = toml.load(f)
        log.debug(f"{self}: Loaded config from .toml:\ndata={data}")
        try:
            self.info = Info(**data["info"])
            self.tunnel = Tunnel(**data["tunnel"])
            log.debug(self.tunnel)
        except KeyError as e:
            log.error(f"{self}: {e}")
            return self

CFG = CFG.from_toml

class Cloudflare(APIGateway):
    def __init__(self, toml: Path = None):
        self.cwd = Path.cwd()
        self.path = Path(self.cwd / "cloudflare_api.toml")
        self.cfg_path = Path(self.cwd / "cloudflare_api_cfg.toml")
        if toml:
            self.cwd = toml.parent
            self.path = toml
        _ = self.cloudflare_cfg
        APIGateway.__init__(self, path=self.path)

    def __repr__(self):
        return f"[Cloudflare.Gateway]"

    @cached_property
    def cloudflare_cfg(self) -> CFG:
        cfg = CFG(self.cfg_path)
        return cfg
    
    @cached_property
    def name(self) -> str:
        domain = self.cloudflare_cfg.info.domain
        n = domain.split(".")
        return n[0]

    # noinspection PyTypeChecker
    @async_cached_property
    async def tunnel(self) -> Tunnel:
        name = f"{self.name}-tunnel"
        name = name.replace(".", "-")
        if self.cloudflare_cfg.tunnel.id == "":
            post = await self.api_post(
                route="tunnel",
                json={
                    "name": f"{name}",
                    "config_src": "cloudflare"
                },
                force_refresh=True
            )
            if post.status == 200:
                meta = post.body["result"]
                tunnel = Tunnel(name=name, id=meta["id"], token=meta["token"], meta=meta)
                self.cloudflare_cfg.tunnel = tunnel
                self.cloudflare_cfg.write()
                log.success(f"{self}: Successfully found tunnel! {self.cloudflare_cfg.tunnel}")
                return tunnel
            if post.status == 409:
                meta = None
                log.warning(f"{self}: Tunnel for {name} already exists!")
                get: Response = await self.api_get(
                    route="tunnel",
                    force_refresh=True
                )
                get: list = get.body["result"]
                for item in get:
                    log.debug(f"{self}: Scanning for {name} in {item}...\n  - item_name={item["name"]}")
                    if item["name"] == name:
                        meta = item
                        log.success(f"{self}: Successfully found {name}!\n  - metadata={item}")
                        break
                cfd = await cloudflared(f"'cloudflared tunnel token {meta["id"]}'", headless=True)
                tunnel = Tunnel(name=name, id=meta["id"], token=cfd.output, meta=meta)
                self.cloudflare_cfg.tunnel = tunnel
                self.cloudflare_cfg.write()
                log.success(f"{self}: Successfully found tunnel! {self.cloudflare_cfg.tunnel}")
                return tunnel
        else:
            log.debug(f"{self}: Found tunnel creds in {self.cloudflare_cfg.path}!")
            return self.cloudflare_cfg.tunnel

    @async_cached_property
    async def connect_server(self):
        try:
            if self.cloudflare_cfg.info.service_url == "": raise RuntimeError(f"Can't launch cloudflared without a service to launch it to!")
        except RuntimeError:
            try: self.cloudflare_cfg.info.service_url = self.url
            except AttributeError: raise RuntimeError
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
            force_refresh=True
        )
        if out.status == 400:
            log.error(f"{self}Failed Ingress Config request={out}")
            raise RuntimeError
        if out.status == 200:
            log.success(f"{self} Successfully updated Ingress Config!:\nreq={out}")
        return out

    @async_cached_property
    async def dns_record(self):
        # record_name = "phazebreak.work"
        # records = asyncio.run(self.receptionist.get("dns_record", append="?zone_id=$ZONE_ID"))
        # record_id = next(r["id"] for r in records.content["result"] if r["name"] == record_name)
        # asyncio.run(self.receptionist.delete(f"dns_record", append=f"{record_id}"))

        name = self.cloudflare_cfg.info.domain
        cfg = {
            "type": "CNAME",
            "proxied": True,
            "name": f"{name}",
            "content": f"{self.cloudflare_cfg.tunnel.id}.cfargotunnel.com"
        }
        out = await self.api_post(route="dns_record", json=cfg, force_refresh=True)
        if out.status == 400 and out.body["errors"][0]["code"] == 81053:
            log.warning(f"{self}DNS Request already exists!\nreq={out}")
            headers = {
                f"X-Auth-Email": f"{self.api_vars["cloudflare_email"]}",
                f"X-Auth-Key": f"{self.api_vars["cloudflare_api_token"]}"
            }

            recs = await self.api_get(route="dns_record", force_refresh=True)
            get: list = recs.body["result"]
            rec = None
            for item in get:
                log.debug(f"{self}: Scanning for {name} in {item}...\n  - item_name={item["name"]}")
                if item["name"] == name:
                    rec = item
                    log.success(f"{self}: Successfully found {name} in DNS Records!\n  - metadata={item}")
                    break
            if rec is None: raise RuntimeError
            rec_id = rec["id"]
            log.debug(f"{name}'s DNS Record is {rec_id}")
            rec = await self.api_request(method="patch", route="dns_record", append=f"/{rec_id}", json=cfg, force_refresh=True)#, override_headers=headers)
            log.debug(rec)
        if out.status == 200:
            log.success(f"{self} Successfully updated Ingress Config!:\nreq={out}")
        return out

    @async_cached_property
    async def cloudflare_thread(self) -> threading.Thread:
        await self.tunnel, await self.connect_server, await self.dns_record
        @ManagedThread
        def _launcher():
            log.debug(f"Attempting to run tunnel...")
            cloudflared(f"'cloudflared tunnel info {self.cloudflare_cfg.tunnel.id}'", headless=True)
            cloudflared(f"'cloudflared tunnel run --token {self.cloudflare_cfg.tunnel.token}'", headless=False)
        return _launcher