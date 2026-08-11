"""推演运行时文件系统：磁盘落盘 + 代表可见性控制。

目录布局示例::

    <scenario>/simulation/26-8-10-21:23/
    ├── reps/
    │   ├── winston_churchill/...
    │   └── ...
    └── submissions/          # 提交副本；owner/scope 为空
        └── <venue_id>/
            └── <primary_owner>+<原文件名>+v<版本号>

代表通过 ``list_visible`` / ``list_writable`` 只能看到 ``reps/`` 下的文件。
``submissions/`` 不出现在上述列表中；代表若要得知某份提交的存在，只能经由
``EventList`` 中对其可见、并索引到该 ``File`` 的事件(如 Instruction / Resolution)。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from scenario.scenario import Scenario

# 引擎/系统身份：可读任意文件；写权限仍要求属于 owner。
SYSTEM_ACTOR = "__system__"

# 提交副本文件名：<primary_owner>+<原文件名>+v<版本号>
_SUBMISSION_NAME_RE = re.compile(r"^(?P<owner>.+)\+(?P<original>.+)\+v(?P<version>\d+)$")
_DESCRIPTION_MAX_LEN = 20


class File:
    """带可见性与写权限的逻辑文件。

    - ``scope``：可读(可见)的代表 ID 集合；空集合表示任何代表都不可见。
    - ``owner``：可写(及扩展 scope/owner)的代表 ID 集合；须为 ``scope`` 的子集。
      空集合表示不可写(用于 submissions 中的提交副本)。
    - ``description``：不超过 20 字的文件简述。
    """

    path: Path
    scope: set[str]

    def __init__(
        self,
        path: Path,
        content: str,
        *,
        owner: str | set[str],
        description: str = "",
        scope: set[str] | None = None,
        filesystem: FileSystem | None = None,
    ) -> None:
        self.path = path
        self.__content = content
        self.__description = _normalize_description(description)
        self.__owner: set[str] = _as_id_set(owner, field="owner")
        self.scope = set(scope) if scope is not None else set(self.__owner)
        self._filesystem = filesystem
        # 提交命名用的主 owner：创建时 owner 集合的首位，后续 add_owner 不改变。
        self.__primary_owner: str | None = next(iter(self.__owner), None)
        self._ensure_owners_in_scope()

    @property
    def owners(self) -> frozenset[str]:
        return frozenset(self.__owner)

    @property
    def primary_owner(self) -> str | None:
        """创建时确定的主 owner；提交文件名使用该 ID。"""
        return self.__primary_owner

    @property
    def description(self) -> str:
        return self.__description

    def set_description(self, actor: str, value: str) -> None:
        """由 owner(或系统)修改简述；提交副本不可改。"""
        if self.is_submission:
            raise PermissionError(f"提交副本不可修改 description: {self.path}")
        if not self.__owner:
            raise PermissionError(f"文件 {self.path} 的 owner 为空，不可修改 description")
        if actor != SYSTEM_ACTOR and actor not in self.__owner:
            raise PermissionError(
                f"对象 {actor!r} 不是文件 {self.path} 的 owner(当前 owner={sorted(self.__owner)})"
            )
        self.__description = _normalize_description(value)

    def _restore_primary_owner(self, primary: str) -> None:
        """仅供 manifest 回读覆盖主 owner。"""
        if self.__owner and primary not in self.__owner:
            raise ValueError(
                f"primary_owner {primary!r} 不在 owner 中(owner={list(self.__owner)})"
            )
        self.__primary_owner = primary

    @property
    def content_hash(self) -> str:
        return _content_hash(self.__content)

    @property
    def is_submission(self) -> bool:
        """是否为 submissions/ 下的提交副本。"""
        if self._filesystem is None:
            return "submissions/" in self.path.as_posix()
        try:
            rel = self.path.resolve().relative_to(self._filesystem.path).as_posix()
        except ValueError:
            return False
        return rel == "submissions" or rel.startswith("submissions/")

    def _raw_content(self) -> str:
        return self.__content

    def _ensure_owners_in_scope(self) -> None:
        missing = self.__owner - self.scope
        if missing:
            joined = "、".join(sorted(missing))
            raise ValueError(f"文件 {self.path} 的 owner 必须同时在 scope 中，缺失: {joined}")

    def _require_owner(self, actor: str) -> None:
        if actor == SYSTEM_ACTOR:
            return
        if actor not in self.__owner:
            raise PermissionError(
                f"对象 {actor!r} 不是文件 {self.path} 的 owner(当前 owner={sorted(self.__owner)})"
            )

    def add_owner(self, actor: str, obj: set[str]) -> None:
        """由现有 owner(或系统)将已在 scope 中的对象提升为 owner。"""
        if self.is_submission:
            raise PermissionError(f"提交副本不可修改 owner: {self.path}")
        self._require_owner(actor)
        newcomers = _as_id_set(obj, field="add_owner.obj")
        for identity in newcomers:
            if identity not in self.scope:
                raise PermissionError(
                    f"不能将 {identity!r} 设为 owner：其不在文件 {self.path} 的 scope "
                    f"(当前 scope={sorted(self.scope)})"
                )
            self.__owner.add(identity)

    def add_scope(self, actor: str, obj: set[str]) -> None:
        """由 owner(或系统)扩大可见范围。"""
        if self.is_submission:
            raise PermissionError(f"提交副本不可修改 scope: {self.path}")
        self._require_owner(actor)
        newcomers = _as_id_set(obj, field="add_scope.obj")
        self.scope.update(newcomers)

    def get_content(self, actor: str) -> str:
        if not self.visible_to(actor):
            raise PermissionError(
                f"对象 {actor!r} 无权读取文件 {self.path}(scope={sorted(self.scope)})"
            )
        return self.__content

    def set_content(self, actor: str, content: str) -> None:
        if not self.__owner:
            raise PermissionError(f"文件 {self.path} 的 owner 为空，不可写入")
        if actor != SYSTEM_ACTOR and actor not in self.__owner:
            raise PermissionError(
                f"对象 {actor!r} 不是文件 {self.path} 的 owner(当前 owner={sorted(self.__owner)})"
            )
        self.__content = content

    def visible_to(self, actor: str) -> bool:
        if actor == SYSTEM_ACTOR:
            return True
        return actor in self.scope

    def can_submit(self, actor: str) -> bool:
        """判断 ``actor`` 是否可将本文件提交到 submissions/。"""
        try:
            self._validate_submission(actor)
        except (PermissionError, ValueError, RuntimeError, FileExistsError):
            return False
        return True

    def _validate_submission(self, actor: str) -> tuple[FileSystem, Path, int]:
        if self._filesystem is None:
            raise RuntimeError(f"文件 {self.path} 未绑定 FileSystem，无法提交")
        fs = self._filesystem
        if actor == SYSTEM_ACTOR:
            raise PermissionError("系统身份不能作为提交者")
        if actor not in fs._known_rep_ids():
            raise ValueError(f"未知代表 ID: {actor}")
        if self.is_submission:
            raise PermissionError(f"提交副本不能再次提交: {self.path}")
        if not self.__owner:
            raise PermissionError(f"owner 为空的文件不可提交: {self.path}")
        if actor not in self.__owner:
            raise PermissionError(
                f"对象 {actor!r} 不是文件 {self.path} 的 owner，不能提交"
            )

        rel = fs._relkey(self.path)
        if not rel.startswith("reps/"):
            raise PermissionError(f"只能提交 reps/ 下的文件，实际为: {rel}")

        primary = self.primary_owner
        if primary is None:
            raise PermissionError(f"owner 为空的文件不可提交: {self.path}")

        venue_id = _venue_id_for_rep(fs.scenario, actor)
        original_name = self.path.name
        latest = fs._latest_submission(venue_id, primary, original_name)
        if latest is not None and latest.content_hash == self.content_hash:
            raise ValueError(
                f"内容相对最新提交未变化(hash={self.content_hash})，拒绝重复提交: "
                f"{fs._relkey(latest.path)}"
            )

        next_version = 1 if latest is None else _submission_version(latest.path.name) + 1
        dest_name = f"{primary}+{original_name}+v{next_version}"
        dest_full = fs._resolve(Path("submissions") / venue_id / dest_name)
        dest_key = fs._relkey(dest_full)
        if dest_key in fs._files or dest_full.exists():
            raise FileExistsError(f"提交目标已存在: {dest_key}")
        return fs, dest_full, next_version

    def submit(self, actor: str) -> File:
        """验证通过后复制到 submissions/。

        文件名：``<primary_owner>+<原文件名>+v<版本号>``。
        与同系列最新版本内容 hash 相同则拒绝；否则分配新版本号。
        提交副本的 owner/scope 均为空集：代表不可见、不可改。
        """
        fs, dest_full, _version = self._validate_submission(actor)
        copy = File(
            dest_full,
            self._raw_content(),
            owner=set(),
            description=self.__description,
            scope=set(),
            filesystem=fs,
        )
        fs._register(copy)
        return copy

    def to_manifest(self, *, root: Path) -> dict[str, object]:
        rel = self.path.relative_to(root).as_posix()
        payload: dict[str, object] = {
            "path": rel,
            "description": self.__description,
            "owner": list(self.__owner),
            "scope": sorted(self.scope),
        }
        if self.__primary_owner is not None:
            payload["primary_owner"] = self.__primary_owner
        if self.is_submission:
            payload["content_hash"] = self.content_hash
        return payload


class FileSystem:
    """绑定单次推演运行目录的文件系统。"""

    path: Path
    scenario: Scenario

    def __init__(self, path: Path, scenario: Scenario) -> None:
        self.path = path.resolve()
        self.scenario = scenario
        self._files: dict[str, File] = {}
        self._ensure_layout()
        self._load_manifest()

    @classmethod
    def create_for_scenario(cls, scenario: Scenario) -> FileSystem:
        """在场景包 ``simulation/`` 下新建「日期+时间」目录并绑定。"""
        root = scenario.root_path
        if root is None:
            raise ValueError("Scenario.root_path 未设置，无法创建 FileSystem；请先 load 场景包")

        run_dir = root / "simulation" / _format_run_dirname(datetime.now())
        if run_dir.exists():
            raise FileExistsError(f"推演目录已存在: {run_dir}")
        run_dir.mkdir(parents=True, exist_ok=False)
        return cls(run_dir, scenario)

    def _known_rep_ids(self) -> set[str]:
        return {rep.id for rep in self.scenario.representatives}

    def _known_venue_ids(self) -> set[str]:
        return {venue.id for venue in self.scenario.venues}

    def _ensure_layout(self) -> None:
        (self.path / "reps").mkdir(parents=True, exist_ok=True)
        submissions = self.path / "submissions"
        submissions.mkdir(parents=True, exist_ok=True)

        for rep in self.scenario.representatives:
            (self.path / "reps" / rep.id).mkdir(parents=True, exist_ok=True)

        for venue in self.scenario.venues:
            (submissions / venue.id).mkdir(parents=True, exist_ok=True)

    def _manifest_path(self) -> Path:
        return self.path / "_manifest.yaml"

    def _relkey(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.path).as_posix()
        except ValueError as exc:
            raise ValueError(f"路径不在 FileSystem 根目录内: {path}(根={self.path})") from exc

    def _resolve(self, relative: str | Path) -> Path:
        rel = Path(relative)
        if rel.is_absolute():
            raise ValueError(f"须使用相对路径: {relative}")
        full = (self.path / rel).resolve()
        try:
            full.relative_to(self.path)
        except ValueError as exc:
            raise ValueError(f"路径越界: {relative}(根={self.path})") from exc
        return full

    def _validate_actors(self, actors: set[str], *, field: str) -> None:
        known = self._known_rep_ids()
        unknown = actors - known
        if unknown:
            joined = "、".join(sorted(unknown))
            raise ValueError(f"{field} 含未知代表 ID: {joined}")

    def _register(self, file: File) -> None:
        key = self._relkey(file.path)
        if key in self._files:
            raise FileExistsError(f"文件已登记: {key}")
        file._filesystem = self
        self._files[key] = file
        self._persist_file(file)

    def _persist_file(self, file: File) -> None:
        file.path.parent.mkdir(parents=True, exist_ok=True)
        file.path.write_text(file._raw_content(), encoding="utf-8")
        self._save_manifest()

    def _save_manifest(self) -> None:
        payload = {
            "files": [
                self._files[key].to_manifest(root=self.path)
                for key in sorted(self._files)
            ]
        }
        self._manifest_path().write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _load_manifest(self) -> None:
        manifest_path = self._manifest_path()
        if not manifest_path.is_file():
            self._save_manifest()
            return

        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"manifest 顶层须为对象: {manifest_path}")
        entries = raw.get("files", [])
        if not isinstance(entries, list):
            raise ValueError(f"manifest.files 须为列表: {manifest_path}")

        for index, entry in enumerate(entries):
            context = f"_manifest.yaml.files[{index}]"
            if not isinstance(entry, dict):
                raise ValueError(f"{context} 须为对象")
            rel = entry.get("path")
            if not isinstance(rel, str) or not rel.strip():
                raise ValueError(f"{context}.path 须为非空字符串")
            full = self._resolve(rel.strip())
            if not full.is_file():
                raise FileNotFoundError(f"{context} 指向的文件不存在: {full}")

            owner_raw = entry.get("owner", [])
            scope_raw = entry.get("scope", [])
            if not isinstance(owner_raw, list) or not isinstance(scope_raw, list):
                raise ValueError(f"{context} 的 owner/scope 须为列表")
            if "writable" in entry:
                raise ValueError(f"{context} 不再支持 writable 字段，请删除后重试")

            description_raw = entry.get("description", "")
            if not isinstance(description_raw, str):
                raise ValueError(f"{context}.description 须为字符串")

            file = File(
                full,
                full.read_text(encoding="utf-8"),
                owner=_ordered_id_set(owner_raw, field=f"{context}.owner"),
                description=description_raw,
                scope=set(str(item) for item in scope_raw),
                filesystem=self,
            )
            primary_raw = entry.get("primary_owner")
            if primary_raw is not None:
                if not isinstance(primary_raw, str) or not primary_raw.strip():
                    raise ValueError(f"{context}.primary_owner 须为非空字符串")
                file._restore_primary_owner(primary_raw.strip())
            self._files[self._relkey(full)] = file

    def create_file(
        self,
        relative_path: str | Path,
        content: str,
        *,
        owner: str | set[str],
        description: str = "",
        scope: set[str] | None = None,
    ) -> File:
        """在运行目录下创建普通文件并登记可见性。

        禁止直接在 ``submissions/`` 下创建；提交请使用 :meth:`File.submit`。
        """
        full = self._resolve(relative_path)
        key = self._relkey(full)
        if key == "submissions" or key.startswith("submissions/"):
            raise ValueError("不能直接在 submissions/ 下创建文件，请使用 File.submit()")
        if key in self._files or full.exists():
            raise FileExistsError(f"文件已存在: {key}")

        owners = _as_id_set(owner, field="owner")
        if not owners:
            raise ValueError(f"create_file({key}) 的 owner 不能为空")
        scopes = set(scope) if scope is not None else set(owners)
        self._validate_actors(owners | scopes, field=f"create_file({key})")

        file = File(
            full,
            content,
            owner=owners,
            description=description,
            scope=scopes,
            filesystem=self,
        )
        self._register(file)
        return file

    def create_rep_file(
        self,
        rep_id: str,
        name: str,
        content: str,
        *,
        description: str = "",
        scope: set[str] | None = None,
        owner: str | set[str] | None = None,
    ) -> File:
        """在 ``reps/<rep_id>/`` 下创建文件；默认仅该代表可见可写。"""
        if rep_id not in self._known_rep_ids():
            raise ValueError(f"未知代表 ID: {rep_id}")
        if not name or name.endswith("/") or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError(f"非法文件名: {name!r}")

        relative = Path("reps") / rep_id / name
        default_owner: set[str] = {rep_id}
        return self.create_file(
            relative,
            content,
            owner=owner if owner is not None else default_owner,
            description=description,
            scope=scope if scope is not None else set(default_owner),
        )

    def get(self, relative_path: str | Path, actor: str) -> File:
        key = self._relkey(self._resolve(relative_path))
        file = self._files.get(key)
        if file is None:
            raise FileNotFoundError(f"未登记的文件: {key}")
        if not file.visible_to(actor):
            raise PermissionError(f"对象 {actor!r} 不可见文件 {key}")
        return file

    def read(self, relative_path: str | Path, actor: str) -> str:
        return self.get(relative_path, actor).get_content(actor)

    def write(self, relative_path: str | Path, actor: str, content: str) -> None:
        file = self.get(relative_path, actor)
        file.set_content(actor, content)
        self._persist_file(file)

    def set_description(
        self, relative_path: str | Path, actor: str, value: str
    ) -> None:
        file = self.get(relative_path, actor)
        file.set_description(actor, value)
        self._save_manifest()

    def add_scope(self, relative_path: str | Path, actor: str, others: set[str]) -> None:
        file = self.get(relative_path, actor)
        newcomers = _as_id_set(others, field="add_scope.others")
        self._validate_actors(newcomers, field=f"add_scope({self._relkey(file.path)})")
        file.add_scope(actor, newcomers)
        self._save_manifest()

    def add_owner(self, relative_path: str | Path, actor: str, others: set[str]) -> None:
        file = self.get(relative_path, actor)
        newcomers = _as_id_set(others, field="add_owner.others")
        self._validate_actors(newcomers, field=f"add_owner({self._relkey(file.path)})")
        file.add_owner(actor, newcomers)
        self._save_manifest()

    def list_visible(self, rep_id: str) -> list[File]:
        """列出 ``rep_id`` 在 ``reps/`` 下可见的文件。

        不含 ``submissions/``：提交副本只能通过 EventList 中对该代表可见的事件索引获知。
        """
        self._require_rep_id(rep_id, field="list_visible.rep_id")
        visible = [
            file
            for key, file in self._files.items()
            if key.startswith("reps/") and file.visible_to(rep_id)
        ]
        return sorted(visible, key=lambda item: self._relkey(item.path))

    def list_writable(self, rep_id: str) -> list[File]:
        """列出 ``rep_id`` 在 ``reps/`` 下可写的文件。

        不含 ``submissions/``：提交副本对代表不可写，也不经由本方法暴露。
        """
        self._require_rep_id(rep_id, field="list_writable.rep_id")
        writable = [
            file
            for key, file in self._files.items()
            if key.startswith("reps/") and rep_id in file.owners
        ]
        return sorted(writable, key=lambda item: self._relkey(item.path))

    def list_all(self) -> list[File]:
        """列出全部已登记文件(仅供系统/调试)。"""
        return sorted(self._files.values(), key=lambda item: self._relkey(item.path))

    def _require_rep_id(self, rep_id: str, *, field: str) -> None:
        if rep_id not in self._known_rep_ids():
            raise ValueError(f"{field} 含未知代表 ID: {rep_id}")

    def _latest_submission(
        self,
        venue_id: str,
        primary_owner: str,
        original_name: str,
    ) -> File | None:
        """查找同系列(primary_owner + 原文件名)的最新提交副本。"""
        prefix = f"submissions/{venue_id}/"
        latest: File | None = None
        latest_version = 0
        for key, file in self._files.items():
            if not key.startswith(prefix):
                continue
            parsed = _parse_submission_name(Path(key).name)
            if parsed is None:
                continue
            owner, original, version = parsed
            if owner != primary_owner or original != original_name:
                continue
            if version >= latest_version:
                latest_version = version
                latest = file
        return latest


def _venue_id_for_rep(scenario: Scenario, rep_id: str) -> str:
    for rep in scenario.representatives:
        if rep.id == rep_id:
            if rep.venue is None:
                raise ValueError(f"代表 {rep_id} 未绑定会场，无法提交")
            return rep.venue.id
    raise ValueError(f"未知代表 ID: {rep_id}")


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_description(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"description 须为字符串，实际为 {type(value).__name__}")
    text = value.strip()
    if len(text) > _DESCRIPTION_MAX_LEN:
        raise ValueError(
            f"description 不能超过 {_DESCRIPTION_MAX_LEN} 字，实际为 {len(text)} 字: {text!r}"
        )
    return text


def _parse_submission_name(name: str) -> tuple[str, str, int] | None:
    matched = _SUBMISSION_NAME_RE.match(name)
    if matched is None:
        return None
    return matched.group("owner"), matched.group("original"), int(matched.group("version"))


def _submission_version(name: str) -> int:
    parsed = _parse_submission_name(name)
    if parsed is None:
        raise ValueError(f"不是合法的提交文件名: {name}")
    return parsed[2]


def _as_id_set(value: str | set[str] | list[str] | frozenset[str], *, field: str) -> set[str]:
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"{field} 不能为空字符串")
        return {value.strip()}
    if isinstance(value, (set, frozenset, list, tuple)):
        return _ordered_id_set(value, field=field)
    raise TypeError(f"{field} 须为 str 或字符串集合，实际为 {type(value).__name__}")


def _ordered_id_set(value: set[str] | list[str] | frozenset[str] | tuple[str, ...], *, field: str) -> set[str]:
    """按输入顺序构建 set(CPython 3.7+ 保留插入序)，以便 primary_owner 稳定。"""
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} 中的每一项须为非空字符串")
        result.add(item.strip())
    return result


def _format_run_dirname(when: datetime) -> str:
    """生成推演目录名，形如 ``26-8-10-21:23``(年取后两位，月日时分不补零)。"""
    return (
        f"{when.year % 100}-{when.month}-{when.day}-"
        f"{when.hour}:{when.minute:02d}"
    )
