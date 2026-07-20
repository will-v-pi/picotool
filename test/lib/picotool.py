"""Thin wrapper around invoking the picotool binary."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field


@dataclass
class Result:
    """The result of one picotool invocation."""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def out(self) -> str:
        """stdout and stderr combined - picotool spreads messages across both."""
        return self.stdout + self.stderr

    def __str__(self) -> str:
        cmd = " ".join(self.args)
        status = "timeout" if self.timed_out else f"rc={self.returncode}"
        return f"$ {cmd}\n[{status}]\n{self.out}"


class PicotoolError(AssertionError):
    def __init__(self, result: Result):
        self.result = result
        super().__init__(str(result))


@dataclass
class Picotool:
    """Runs the picotool binary and captures its output."""

    exe: str
    default_timeout: float = 60.0
    log: list[Result] = field(default_factory=list)

    def run(
        self,
        *args,
        check: bool = False,
        timeout: float | None = None,
        input: str | None = None,
    ) -> Result:
        cmd = [self.exe] + [str(a) for a in args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self.default_timeout,
                input=input,
            )
            result = Result(cmd, proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired as e:
            result = Result(
                cmd,
                returncode=-1,
                stdout=e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                stderr=e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""),
                timed_out=True,
            )
        self.log.append(result)
        if check and not result.ok:
            raise PicotoolError(result)
        return result

    def ok(self, *args, **kwargs) -> Result:
        """Run and assert success."""
        return self.run(*args, check=True, **kwargs)
