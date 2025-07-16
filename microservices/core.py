import time
from typing import Any

from starlette.requests import Request

from fast_auth import FastAuth

class Microservice(FastAuth):
    quick_cache: {str, str} = {}

    def __init__(self,
                 host: str = "localhost",
                 port: int = None,
                 verbose: bool = True):
        super().__init__(
            host=host,
            port=port,
            verbose=verbose
        )

        @self.get("/quick_cache/{key}")
        def quick_cache_get(key):
            try:
                return self.quick_cache.get(key)
            except KeyError:
                return "404"

        @self.post("/quick_cache/{key}/{value}")
        def quick_cache_post(key, value):
            self.quick_cache.__setitem__(key, value)

Microservice().thread.start()

time.sleep(900)
