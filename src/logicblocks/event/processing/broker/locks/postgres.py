import hashlib
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from psycopg import AsyncConnection, AsyncCursor
from psycopg.rows import scalar_row
from psycopg.sql import SQL
from psycopg_pool import AsyncConnectionPool

from logicblocks.event.db.postgres import ConnectionSettings, ConnectionSource

from .base import Lock, LockManager


def get_digest(lock_id: str) -> int:
    return (
        int(hashlib.sha256(lock_id.encode("utf-8")).hexdigest(), 16) % 10**16
    )


async def _try_lock(cursor: AsyncCursor[Any], lock_name: str) -> bool:
    lock_result = await cursor.execute(
        SQL("SELECT pg_try_advisory_xact_lock(%(lock_id)s)"),
        {"lock_id": get_digest(lock_name)},
    )
    return bool(await lock_result.fetchone())


class PostgresLockManager(LockManager):
    connection_pool: AsyncConnectionPool[AsyncConnection]

    def __init__(self, connection_source: ConnectionSource):
        if isinstance(connection_source, ConnectionSettings):
            self._connection_pool_owner = True
            self.connection_pool = AsyncConnectionPool[AsyncConnection](
                connection_source.to_connection_string(), open=False
            )
        else:
            self._connection_pool_owner = False
            self.connection_pool = connection_source

    @asynccontextmanager
    async def try_lock(self, lock_name: str) -> AsyncGenerator[Lock, None]:
        async with self.connection_pool.connection() as conn:
            async with conn.cursor(row_factory=scalar_row) as cursor:
                locked = await _try_lock(cursor, lock_name)
                yield Lock(
                    name=lock_name,
                    locked=locked,
                    timed_out=False,
                )

    @asynccontextmanager
    async def wait_for_lock(
        self, lock_name: str, *, timeout: timedelta | None = None
    ) -> AsyncGenerator[Lock, None]:
        start = time.monotonic_ns()

        async with self.connection_pool.connection() as conn:
            async with conn.cursor(row_factory=scalar_row) as cursor:
                locked = False

                while not locked and (
                    time.monotonic_ns() < start + (timeout.microseconds * 1000)
                    if timeout
                    else True
                ):
                    locked = await _try_lock(cursor, lock_name)

                end = time.monotonic_ns()
                wait_time = (end - start) / 1000 / 1000

                yield Lock(
                    name=lock_name,
                    locked=locked,
                    timed_out=(not locked),
                    wait_time=timedelta(milliseconds=wait_time),
                )

    # wait for lock -> pg_advisory_xact_lock
    #               -> pg_advisory_lock
    # try lock -> pg_try_advisory_xact_lock
    #          -> pg_try_advisory_lock
    # not sure which to use
    #
    # should the postgres lock manager manage its own dedicated connection?
    # how long running can this connection be?
