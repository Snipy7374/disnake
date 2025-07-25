# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import datetime
import inspect
import sys
import traceback
import warnings
from collections.abc import Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    Generic,
    List,
    Optional,
    Protocol,
    Type,
    TypeVar,
    Union,
    cast,
    get_origin,
    overload,
)

import aiohttp

import disnake
from disnake.backoff import ExponentialBackoff
from disnake.utils import MISSING, utcnow

if TYPE_CHECKING:
    from typing_extensions import Concatenate, ParamSpec, Self

    P = ParamSpec("P")

else:
    P = TypeVar("P")

__all__ = ("loop",)

T = TypeVar("T")
_func = Callable[..., Coroutine[Any, Any, Any]]
LF = TypeVar("LF", bound=_func)
FT = TypeVar("FT", bound=_func)
ET = TypeVar("ET", bound=Callable[[Any, BaseException], Coroutine[Any, Any, Any]])


class SleepHandle:
    __slots__ = ("future", "loop", "handle")

    def __init__(self, dt: datetime.datetime, *, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.future: asyncio.Future[bool] = loop.create_future()
        relative_delta = disnake.utils.compute_timedelta(dt)
        self.handle = loop.call_later(relative_delta, self.future.set_result, True)

    def recalculate(self, dt: datetime.datetime) -> None:
        self.handle.cancel()
        relative_delta = disnake.utils.compute_timedelta(dt)
        self.handle = self.loop.call_later(relative_delta, self.future.set_result, True)

    def wait(self) -> asyncio.Future[bool]:
        return self.future

    def done(self) -> bool:
        return self.future.done()

    def cancel(self) -> None:
        self.handle.cancel()
        self.future.cancel()


class Loop(Generic[LF]):
    """A background task helper that abstracts the loop and reconnection logic for you.

    The main interface to create this is through :func:`loop`.
    """

    def __init__(
        self,
        coro: LF,
        *,
        seconds: float = 0,
        minutes: float = 0,
        hours: float = 0,
        time: Union[datetime.time, Sequence[datetime.time]] = MISSING,
        count: Optional[int] = None,
        reconnect: bool = True,
        loop: asyncio.AbstractEventLoop = MISSING,
    ) -> None:
        """.. note:
        If you overwrite ``__init__`` arguments, make sure to redefine .clone too.
        """
        self.coro: LF = coro
        self.reconnect: bool = reconnect
        self.loop: asyncio.AbstractEventLoop = loop
        self.count: Optional[int] = count
        self._current_loop = 0
        self._handle: SleepHandle = MISSING
        self._task: asyncio.Task[None] = MISSING
        self._injected: Any = None
        self._valid_exception = (
            OSError,
            disnake.GatewayNotFound,
            disnake.ConnectionClosed,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        )

        self._before_loop = None
        self._after_loop = None
        self._is_being_cancelled = False
        self._has_failed = False
        self._stop_next_iteration = False

        if self.count is not None and self.count <= 0:
            raise ValueError("count must be greater than 0 or None.")

        self.change_interval(seconds=seconds, minutes=minutes, hours=hours, time=time)
        self._last_iteration_failed = False
        self._last_iteration: datetime.datetime = MISSING
        self._next_iteration = None

        if not asyncio.iscoroutinefunction(self.coro):
            raise TypeError(f"Expected coroutine function, not {type(self.coro).__name__!r}.")

    async def _call_loop_function(self, name: str, *args: Any, **kwargs: Any) -> None:
        coro = getattr(self, "_" + name)
        if coro is None:
            return

        if self._injected is not None:
            await coro(self._injected, *args, **kwargs)
        else:
            await coro(*args, **kwargs)

    def _try_sleep_until(self, dt: datetime.datetime):
        self._handle = SleepHandle(dt=dt, loop=self.loop)
        return self._handle.wait()

    async def _loop(self, *args: Any, **kwargs: Any) -> None:
        backoff = ExponentialBackoff()
        await self._call_loop_function("before_loop")
        self._last_iteration_failed = False
        if self._time is not MISSING:
            # the time index should be prepared every time the internal loop is started
            self._prepare_time_index()
            self._next_iteration = self._get_next_sleep_time()
        else:
            self._next_iteration = utcnow()
        try:
            await self._try_sleep_until(self._next_iteration)
            while True:
                if not self._last_iteration_failed:
                    self._last_iteration = self._next_iteration
                    self._next_iteration = self._get_next_sleep_time()
                try:
                    await self.coro(*args, **kwargs)
                    self._last_iteration_failed = False
                except self._valid_exception:
                    self._last_iteration_failed = True
                    if not self.reconnect:
                        raise
                    await asyncio.sleep(backoff.delay())
                else:
                    await self._try_sleep_until(self._next_iteration)

                    if self._stop_next_iteration:
                        return

                    now = utcnow()
                    if now > self._next_iteration:
                        self._next_iteration = now
                        if self._time is not MISSING:
                            self._prepare_time_index(now)

                    self._current_loop += 1
                    if self._current_loop == self.count:
                        break

        except asyncio.CancelledError:
            self._is_being_cancelled = True
            raise
        except Exception as exc:
            self._has_failed = True
            await self._call_loop_function("error", exc)
            raise
        finally:
            await self._call_loop_function("after_loop")
            self._handle.cancel()
            self._is_being_cancelled = False
            self._current_loop = 0
            self._stop_next_iteration = False
            self._has_failed = False

    def __get__(self, obj: T, objtype: Type[T]) -> Self:
        if obj is None:
            return self
        clone = self.clone()
        clone._injected = obj
        setattr(obj, self.coro.__name__, clone)
        return clone

    def clone(self) -> Self:
        instance = type(self)(
            self.coro,
            seconds=self._seconds,
            hours=self._hours,
            minutes=self._minutes,
            time=self._time,
            count=self.count,
            reconnect=self.reconnect,
            loop=self.loop,
        )
        instance._before_loop = self._before_loop
        instance._after_loop = self._after_loop
        instance._error = self._error
        instance._injected = self._injected
        return instance

    @property
    def seconds(self) -> Optional[float]:
        """Optional[:class:`float`]: Read-only value for the number of seconds
        between each iteration. ``None`` if an explicit ``time`` value was passed instead.

        .. versionadded:: 2.0
        """
        if self._seconds is not MISSING:
            return self._seconds

    @property
    def minutes(self) -> Optional[float]:
        """Optional[:class:`float`]: Read-only value for the number of minutes
        between each iteration. ``None`` if an explicit ``time`` value was passed instead.

        .. versionadded:: 2.0
        """
        if self._minutes is not MISSING:
            return self._minutes

    @property
    def hours(self) -> Optional[float]:
        """Optional[:class:`float`]: Read-only value for the number of hours
        between each iteration. ``None`` if an explicit ``time`` value was passed instead.

        .. versionadded:: 2.0
        """
        if self._hours is not MISSING:
            return self._hours

    @property
    def time(self) -> Optional[List[datetime.time]]:
        """Optional[List[:class:`datetime.time`]]: Read-only list for the exact times this loop runs at.
        ``None`` if relative times were passed instead.

        .. versionadded:: 2.0
        """
        if self._time is not MISSING:
            return self._time.copy()

    @property
    def current_loop(self) -> int:
        """:class:`int`: The current iteration of the loop."""
        return self._current_loop

    @property
    def next_iteration(self) -> Optional[datetime.datetime]:
        """Optional[:class:`datetime.datetime`]: When the next iteration of the loop will occur.

        .. versionadded:: 1.3
        """
        if self._task is MISSING:
            return None
        elif (self._task and self._task.done()) or self._stop_next_iteration:
            return None
        return self._next_iteration

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """|coro|

        Calls the internal callback that the task holds.

        .. versionadded:: 1.6

        Parameters
        ----------
        *args
            The arguments to use.
        **kwargs
            The keyword arguments to use.
        """
        if self._injected is not None:
            args = (self._injected, *args)

        return await self.coro(*args, **kwargs)

    def start(self, *args: Any, **kwargs: Any) -> asyncio.Task[None]:
        """Starts the internal task in the event loop.

        Parameters
        ----------
        *args
            The arguments to use.
        **kwargs
            The keyword arguments to use.

        Raises
        ------
        RuntimeError
            A task has already been launched and is running.

        Returns
        -------
        :class:`asyncio.Task`
            The task that has been created.
        """
        if self._task is not MISSING and not self._task.done():
            raise RuntimeError("Task is already launched and is not completed.")

        if self._injected is not None:
            args = (self._injected, *args)

        if self.loop is MISSING:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                self.loop = asyncio.get_event_loop()

        self._task = self.loop.create_task(self._loop(*args, **kwargs))
        return self._task

    def stop(self) -> None:
        """Gracefully stops the task from running.

        Unlike :meth:`cancel`\\, this allows the task to finish its
        current iteration before gracefully exiting.

        .. note::

            If the internal function raises an error that can be
            handled before finishing then it will retry until
            it succeeds.

            If this is undesirable, either remove the error handling
            before stopping via :meth:`clear_exception_types` or
            use :meth:`cancel` instead.

        .. versionadded:: 1.2
        """
        if self._task is not MISSING and not self._task.done():
            self._stop_next_iteration = True

    def _can_be_cancelled(self) -> bool:
        return bool(not self._is_being_cancelled and self._task and not self._task.done())

    def cancel(self) -> None:
        """Cancels the internal task, if it is running."""
        if self._can_be_cancelled():
            self._task.cancel()

    def restart(self, *args: Any, **kwargs: Any) -> None:
        """A convenience method to restart the internal task.

        .. note::

            Due to the way this function works, the task is not
            returned like :meth:`start`.

        Parameters
        ----------
        *args
            The arguments to use.
        **kwargs
            The keyword arguments to use.
        """

        def restart_when_over(fut: Any, *, args: Any = args, kwargs: Any = kwargs) -> None:
            self._task.remove_done_callback(restart_when_over)
            self.start(*args, **kwargs)

        if self._can_be_cancelled():
            self._task.add_done_callback(restart_when_over)
            self._task.cancel()

    def add_exception_type(self, *exceptions: Type[BaseException]) -> None:
        """Adds exception types to be handled during the reconnect logic.

        By default the exception types handled are those handled by
        :meth:`disnake.Client.connect`\\, which includes a lot of internet disconnection
        errors.

        This function is useful if you're interacting with a 3rd party library that
        raises its own set of exceptions.

        Parameters
        ----------
        *exceptions: Type[:class:`BaseException`]
            An argument list of exception classes to handle.

        Raises
        ------
        TypeError
            An exception passed is either not a class or not inherited from :class:`BaseException`.
        """
        for exc in exceptions:
            if not inspect.isclass(exc):
                raise TypeError(f"{exc!r} must be a class.")
            if not issubclass(exc, BaseException):
                raise TypeError(f"{exc!r} must inherit from BaseException.")

        self._valid_exception = (*self._valid_exception, *exceptions)

    def clear_exception_types(self) -> None:
        """Removes all exception types that are handled.

        .. note::

            This operation obviously cannot be undone!
        """
        self._valid_exception = ()

    def remove_exception_type(self, *exceptions: Type[BaseException]) -> bool:
        """Removes exception types from being handled during the reconnect logic.

        Parameters
        ----------
        *exceptions: Type[:class:`BaseException`]
            An argument list of exception classes to handle.

        Returns
        -------
        :class:`bool`
            Whether all exceptions were successfully removed.
        """
        old_length = len(self._valid_exception)
        self._valid_exception = tuple(x for x in self._valid_exception if x not in exceptions)
        return len(self._valid_exception) == old_length - len(exceptions)

    def get_task(self) -> Optional[asyncio.Task[None]]:
        """Fetches the internal task or ``None`` if there isn't one running.

        :return type: Optional[:class:`asyncio.Task`]
        """
        return self._task if self._task is not MISSING else None

    def is_being_cancelled(self) -> bool:
        """Whether the task is being cancelled.

        :return type: :class:`bool`
        """
        return self._is_being_cancelled

    def failed(self) -> bool:
        """Whether the internal task has failed.

        .. versionadded:: 1.2

        :return type: :class:`bool`
        """
        return self._has_failed

    def is_running(self) -> bool:
        """Check if the task is currently running.

        .. versionadded:: 1.4

        :return type: :class:`bool`
        """
        return not bool(self._task.done()) if self._task is not MISSING else False

    async def _error(self, *args: Any) -> None:
        exception: Exception = args[-1]
        print(
            f"Unhandled exception in internal background task {self.coro.__name__!r}.",
            file=sys.stderr,
        )
        traceback.print_exception(
            type(exception), exception, exception.__traceback__, file=sys.stderr
        )

    def before_loop(self, coro: FT) -> FT:
        """A decorator that registers a coroutine to be called before the loop starts running.

        This is useful if you want to wait for some bot state before the loop starts,
        such as :meth:`disnake.Client.wait_until_ready`.

        The coroutine must take no arguments (except ``self`` in a class context).

        Parameters
        ----------
        coro: :ref:`coroutine <coroutine>`
            The coroutine to register before the loop runs.

        Raises
        ------
        TypeError
            The function was not a coroutine.
        """
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError(f"Expected coroutine function, received {coro.__class__.__name__!r}.")

        self._before_loop = coro
        return coro

    def after_loop(self, coro: FT) -> FT:
        """A decorator that register a coroutine to be called after the loop finished running.

        The coroutine must take no arguments (except ``self`` in a class context).

        .. note::

            This coroutine is called even during cancellation. If it is desirable
            to tell apart whether something was cancelled or not, check to see
            whether :meth:`is_being_cancelled` is ``True`` or not.

        Parameters
        ----------
        coro: :ref:`coroutine <coroutine>`
            The coroutine to register after the loop finishes.

        Raises
        ------
        TypeError
            The function was not a coroutine.
        """
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError(f"Expected coroutine function, received {coro.__class__.__name__!r}.")

        self._after_loop = coro
        return coro

    def error(self, coro: ET) -> ET:
        """A decorator that registers a coroutine to be called if the task encounters an unhandled exception.

        The coroutine must take only one argument the exception raised (except ``self`` in a class context).

        By default this prints to :data:`sys.stderr` however it could be
        overridden to have a different implementation.

        .. versionadded:: 1.4

        Parameters
        ----------
        coro: :ref:`coroutine <coroutine>`
            The coroutine to register in the event of an unhandled exception.

        Raises
        ------
        TypeError
            The function was not a coroutine.
        """
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError(f"Expected coroutine function, received {coro.__class__.__name__!r}.")

        self._error = coro  # type: ignore
        return coro

    def _get_next_sleep_time(self) -> datetime.datetime:
        if self._sleep is not MISSING:
            return self._last_iteration + datetime.timedelta(seconds=self._sleep)

        if self._time_index >= len(self._time):
            self._time_index = 0
            if self._current_loop == 0:
                # if we're at the last index on the first iteration, we need to sleep until tomorrow
                return datetime.datetime.combine(
                    utcnow() + datetime.timedelta(days=1),
                    self._time[0],
                )

        next_time = self._time[self._time_index]

        if self._current_loop == 0:
            self._time_index += 1
            if next_time > utcnow().timetz():
                return datetime.datetime.combine(utcnow(), next_time)
            else:
                return datetime.datetime.combine(
                    utcnow() + datetime.timedelta(days=1),
                    next_time,
                )

        next_date = self._last_iteration
        if next_time < next_date.timetz():
            next_date += datetime.timedelta(days=1)

        self._time_index += 1
        return datetime.datetime.combine(next_date, next_time)

    def _prepare_time_index(self, now: datetime.datetime = MISSING) -> None:
        # now kwarg should be a datetime.datetime representing the time "now"
        # to calculate the next time index from

        # pre-condition: self._time is set
        time_now = (now if now is not MISSING else utcnow().replace(microsecond=0)).timetz()
        for idx, time in enumerate(self._time):
            if time >= time_now:
                self._time_index = idx
                break
        else:
            self._time_index = 0

    def _get_time_parameter(
        self,
        time: Union[datetime.time, Sequence[datetime.time]],
        *,
        dt: Type[datetime.time] = datetime.time,
        utc: datetime.timezone = datetime.timezone.utc,
    ) -> List[datetime.time]:
        if isinstance(time, dt):
            inner = time if time.tzinfo is not None else time.replace(tzinfo=utc)
            return [inner]
        if not isinstance(time, Sequence):
            raise TypeError(
                f"Expected datetime.time or a sequence of datetime.time for ``time``, received {type(time)!r} instead."
            )
        if not time:
            raise ValueError("time parameter must not be an empty sequence.")

        ret: List[datetime.time] = []
        for index, t in enumerate(time):
            if not isinstance(t, dt):
                raise TypeError(
                    f"Expected a sequence of {dt!r} for ``time``, received {type(t).__name__!r} at index {index} instead."
                )
            ret.append(t if t.tzinfo is not None else t.replace(tzinfo=utc))

        ret = sorted(set(ret))  # de-dupe and sort times
        return ret

    def change_interval(
        self,
        *,
        seconds: float = 0,
        minutes: float = 0,
        hours: float = 0,
        time: Union[datetime.time, Sequence[datetime.time]] = MISSING,
    ) -> None:
        """Changes the interval for the sleep time.

        .. versionadded:: 1.2

        Parameters
        ----------
        seconds: :class:`float`
            The number of seconds between every iteration.
        minutes: :class:`float`
            The number of minutes between every iteration.
        hours: :class:`float`
            The number of hours between every iteration.
        time: Union[:class:`datetime.time`, Sequence[:class:`datetime.time`]]
            The exact times to run this loop at. Either a non-empty list or a single
            value of :class:`datetime.time` should be passed.
            This cannot be used in conjunction with the relative time parameters.

            .. versionadded:: 2.0

            .. note::

                Duplicate times will be ignored, and only run once.

        Raises
        ------
        ValueError
            An invalid value was given.
        TypeError
            An invalid value for the ``time`` parameter was passed, or the
            ``time`` parameter was passed in conjunction with relative time parameters.
        """
        if time is MISSING:
            seconds = seconds or 0
            minutes = minutes or 0
            hours = hours or 0
            sleep = seconds + (minutes * 60.0) + (hours * 3600.0)
            if sleep < 0:
                raise ValueError("Total number of seconds cannot be less than zero.")

            self._sleep = sleep
            self._seconds = float(seconds)
            self._hours = float(hours)
            self._minutes = float(minutes)
            self._time: List[datetime.time] = MISSING
        else:
            if any((seconds, minutes, hours)):
                raise TypeError("Cannot mix explicit time with relative time")
            self._time = self._get_time_parameter(time)
            self._sleep = self._seconds = self._minutes = self._hours = MISSING

        # `_last_iteration` can be missing if `change_interval` gets called in `before_loop` or
        # before the event loop ticks after `start()`
        if self.is_running() and self._last_iteration is not MISSING:
            if self._time is not MISSING:
                # prepare the next time index starting from after the last iteration
                self._prepare_time_index(now=self._last_iteration)

            self._next_iteration = self._get_next_sleep_time()
            if not self._handle.done():
                # the loop is sleeping, recalculate based on new interval
                self._handle.recalculate(self._next_iteration)


T_co = TypeVar("T_co", covariant=True)
L_co = TypeVar("L_co", bound=Loop, covariant=True)


class Object(Protocol[T_co, P]):
    def __new__(cls) -> T_co: ...

    def __init__(self, *args: P.args, **kwargs: P.kwargs) -> None: ...


@overload
def loop(
    *,
    seconds: float = ...,
    minutes: float = ...,
    hours: float = ...,
    time: Union[datetime.time, Sequence[datetime.time]] = ...,
    count: Optional[int] = None,
    reconnect: bool = True,
    loop: asyncio.AbstractEventLoop = ...,
) -> Callable[[LF], Loop[LF]]: ...


@overload
def loop(
    cls: Type[Object[L_co, Concatenate[LF, P]]], *_: P.args, **kwargs: P.kwargs
) -> Callable[[LF], L_co]: ...


def loop(
    cls: Type[Object[L_co, Concatenate[LF, P]]] = Loop[Any],
    **kwargs: Any,
) -> Callable[[LF], L_co]:
    """A decorator that schedules a task in the background for you with
    optional reconnect logic. The decorator returns a :class:`Loop`.

    Parameters
    ----------
    cls: Type[:class:`Loop`]
        The loop subclass to create an instance of. If provided, the following parameters
        described below do not apply. Instead, this decorator will accept the same keywords
        as the passed cls does.

        .. versionadded:: 2.6

    seconds: :class:`float`
        The number of seconds between every iteration.
    minutes: :class:`float`
        The number of minutes between every iteration.
    hours: :class:`float`
        The number of hours between every iteration.
    time: Union[:class:`datetime.time`, Sequence[:class:`datetime.time`]]
        The exact times to run this loop at. Either a non-empty list or a single
        value of :class:`datetime.time` should be passed. Timezones are supported.
        If no timezone is given for the times, it is assumed to represent UTC time.

        This cannot be used in conjunction with the relative time parameters.

        .. note::

            Duplicate times will be ignored, and only run once.

        .. versionadded:: 2.0

    count: Optional[:class:`int`]
        The number of loops to do, ``None`` if it should be an
        infinite loop.
    reconnect: :class:`bool`
        Whether to handle errors and restart the task
        using an exponential back-off algorithm similar to the
        one used in :meth:`disnake.Client.connect`.
    loop: :class:`asyncio.AbstractEventLoop`
        The loop to use to register the task, if not given
        defaults to :func:`asyncio.get_event_loop`.

    Raises
    ------
    ValueError
        An invalid value was given.
    TypeError
        The function was not a coroutine, the ``cls`` parameter was not a subclass of ``Loop``,
        an invalid value for the ``time`` parameter was passed,
        or ``time`` parameter was passed in conjunction with relative time parameters.
    """
    if (origin := get_origin(cls)) is not None:
        cls = origin

    if not isinstance(cls, type) or not issubclass(cls, Loop):
        raise TypeError(f"cls argument must be a subclass of Loop, got {cls!r}")

    def decorator(func: LF) -> L_co:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("decorated function must be a coroutine")

        return cast("Type[L_co]", cls)(func, **kwargs)

    return decorator
