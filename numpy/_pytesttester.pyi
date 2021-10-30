from typing import List, Iterable, Literal as L

__all__: List[str]

class PytestTester:
    module_name: str
    def __init__(self, module_name: str) -> None: ...
    def __call__(
        self,
        label: L["fast", "full"] = ...,
        verbose: int = ...,
        extra_argv: None | Iterable[str] = ...,
        doctests: L[False] = ...,
        coverage: bool = ...,
        durations: int = ...,
        tests: None | Iterable[str] = ...,
        pdb: bool = ...,
        pdbcls: None | str = ...,
    ) -> bool: ...
