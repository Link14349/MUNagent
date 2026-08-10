from pathlib import Path
from scenario.scenario import Scenario


""""
文件系统

例: filesystem管理的路径/scenario-template/simulation/26-8-10-21:23/, 内含
|- reps
|  |- rep1/xxx.md
|  |- rep2/xxx.md
|  |- ...
|- submissions(submissions都是不可编辑&代表不可见的)
|  |- venue1/
|  |  |- instructions/
|  |  |- notes/
|  |- ...
"""

class File:
    path: Path
    __content: str
    scope: set[str]
    __writable: bool
    __owner: set[str]
    def __init__(self, path: Path, content: str, owner: str, writable: bool, scope: set[str]):
        self.path = path
        self.__content = content
        self.scope = scope
        self.__writable = writable
        self.__owner = set(owner)
    
    def add_owner(self, obj: set[str]) -> None:
        for o in obj:
            if o not in self.scope:
                raise PermissionError(f"Object {o} not in scope {self.scope}")
            self.__owner.add(o)
    
    def add_scope(self, obj: set[str]) -> None:
        for o in obj:
            if o not in self.__owner:
                raise PermissionError(f"Object {o} not in owner {self.__owner}")
            self.__owner.add(o)
    
    def get_content(self, obj: str) -> str:
        if obj not in self.scope:
            raise PermissionError(f"Object {obj} not in scope {self.scope}")
        return self.__content

    def set_content(self, obj: str, content: str) -> None:
        if not self.__writable:
            raise PermissionError("File is not writable")
        if obj not in self.__owner:
            raise PermissionError(f"Object {obj} not in owner {self.__owner}")
        self.__content = content
    
    def visible_to(self, obj: str) -> bool:
        if obj not in self.scope:
            return False
        return True

class FileSystem:
    def __init__(self, path: Path, scenario: Scenario):
        self.path = path
        self.scenario = scenario
        