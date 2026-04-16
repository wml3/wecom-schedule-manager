#!/usr/bin/env python
"""
企业微信日程管理命令行工具。

本脚本不会内置真实租户参数。请通过命令行参数、环境变量或 UTF-8 请求
文件提供运行时所需配置，具体说明见 references/configuration.md。
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"
DEFAULT_TIMEZONE = timezone(timedelta(hours=8))


def configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def env_or_value(value: Optional[str], env_name: str, required: bool = False) -> Optional[str]:
    resolved = value or os.getenv(env_name)
    if required and not resolved:
        raise SystemExit(f"缺少必填参数：--{env_name.lower().replace('_', '-')} 或环境变量 {env_name}")
    return resolved


def parse_json(text: Optional[str], default: Any) -> Any:
    if not text:
        return default
    return json.loads(text)


def read_utf8_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8-sig").strip()


def read_utf8_json_text(path: str) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return json.dumps(payload, ensure_ascii=False)


def read_stdin_json_text() -> str:
    return sys.stdin.read()


def looks_garbled_text(value: Optional[str]) -> bool:
    if not value:
        return False
    if "?" not in value:
        return False
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", value))
    many_question_marks = value.count("?") >= 2
    return many_question_marks and not has_cjk


def guard_against_garbled_text(args: argparse.Namespace) -> None:
    risky_fields = {
        "summary": args.summary,
        "description": args.description,
        "location": args.location,
        "content": args.content,
    }
    bad_fields = [name for name, value in risky_fields.items() if looks_garbled_text(value)]
    if bad_fields:
        raise SystemExit(
            "检测到可能的乱码字段："
            + ", ".join(f"--{field}" for field in bad_fields)
            + "。请改用 UTF-8 文件输入，例如 --request-file、--summary-file、"
              "--description-file、--location-file 或 --content-file。"
        )


def parse_time(value: str) -> int:
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=DEFAULT_TIMEZONE)
    return int(dt.timestamp())


def iso_now() -> str:
    return datetime.now(tz=DEFAULT_TIMEZONE).isoformat()


def ensure_wecom_channel(channel: str) -> None:
    if channel != "wecom":
        raise SystemExit("这个 skill 只允许使用企业微信通道。请传入 --channel wecom。")


def compact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: compact_payload(v) for k, v in payload.items() if v is not None}
    if isinstance(payload, list):
        return [compact_payload(v) for v in payload]
    return payload


def write_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


@dataclass
class AuditContext:
    path: Path
    request_id: str
    channel: str
    operator_id: Optional[str]

    def append(self, event_type: str, detail: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": iso_now(),
            "request_id": self.request_id,
            "channel": self.channel,
            "operator_id": self.operator_id,
            "event_type": event_type,
            "detail": detail,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


class CalendarBindingStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: Optional[Dict[str, Any]] = None

    def _load(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        else:
            self._data = {"version": 1, "bindings": {}}
        self._data.setdefault("version", 1)
        self._data.setdefault("bindings", {})
        return self._data

    def _save(self) -> None:
        data = self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _binding_key(corp_id: str, agent_id: str, user_id: str) -> str:
        return f"{corp_id}:{agent_id}:{user_id}"

    def get(self, *, corp_id: str, agent_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        bindings = self._load()["bindings"]
        return bindings.get(self._binding_key(corp_id, agent_id, user_id))

    def set(
        self,
        *,
        corp_id: str,
        agent_id: str,
        user_id: str,
        user_name: Optional[str],
        cal_id: str,
        source: str,
    ) -> Dict[str, Any]:
        record = {
            "corp_id": corp_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "user_name": user_name,
            "cal_id": cal_id,
            "source": source,
            "updated_at": iso_now(),
        }
        self._load()["bindings"][self._binding_key(corp_id, agent_id, user_id)] = record
        self._save()
        return record


class WeComError(RuntimeError):
    def __init__(self, message: str, response: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.response = response or {}


class WeComClient:
    def __init__(self, corp_id: str, corp_secret: str, agent_id: str, audit: AuditContext) -> None:
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = int(agent_id)
        self.audit = audit
        self._access_token: Optional[str] = None
        self._directory_cache: Dict[str, Dict[str, Any]] = {}
        self._department_tree_cache: Dict[str, Dict[str, Any]] = {}
        self.session = requests.Session()
        self.headers = {"Content-Type": "application/json"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        audit_event: Optional[str] = None,
        audit_detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        response = self.session.request(
            method=method,
            url=url,
            params=params,
            json=json_body,
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if audit_event:
            safe_params = {}
            for key, value in (params or {}).items():
                if key in {"access_token", "corpsecret", "secret"}:
                    continue
                safe_params[key] = value
            audit_payload = {
                "path": path,
                "params": compact_payload(safe_params),
                "request": compact_payload(audit_detail or json_body or {}),
                "response": {
                    "errcode": payload.get("errcode"),
                    "errmsg": payload.get("errmsg"),
                },
            }
            self.audit.append(audit_event, audit_payload)
        if payload.get("errcode", 0) != 0:
            raise WeComError(
                f"企业微信接口调用失败 {path}: {payload.get('errcode')} {payload.get('errmsg')}",
                payload,
            )
        return payload

    def get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        payload = self._request(
            "GET",
            "/gettoken",
            params={"corpid": self.corp_id, "corpsecret": self.corp_secret},
            audit_event="token.fetch",
            audit_detail={"corpid": self.corp_id},
        )
        self._access_token = payload["access_token"]
        return self._access_token

    def _authed_params(self, **extra: Any) -> Dict[str, Any]:
        params = {"access_token": self.get_access_token()}
        params.update(extra)
        return params

    def list_departments(self, department_id: Optional[int] = None) -> List[Dict[str, Any]]:
        params = self._authed_params()
        if department_id is not None:
            params["id"] = department_id
        payload = self._request("GET", "/department/list", params=params)
        return payload.get("department") or []

    def list_department_users(self, department_id: int, *, fetch_child: int = 0) -> List[Dict[str, Any]]:
        payload = self._request(
            "GET",
            "/user/simplelist",
            params=self._authed_params(department_id=department_id, fetch_child=fetch_child),
        )
        return payload.get("userlist") or []

    def _build_department_tree(self, root_department_id: int) -> Dict[str, Any]:
        cache_key = str(root_department_id)
        cached = self._department_tree_cache.get(cache_key)
        if cached:
            return cached

        departments = self.list_departments(department_id=root_department_id)
        by_id = {
            int(item["id"]): item
            for item in departments
            if item.get("id") is not None
        }
        children: Dict[int, List[int]] = {}
        for item in departments:
            if item.get("id") is None or item.get("parentid") is None:
                continue
            parent_id = int(item["parentid"])
            children.setdefault(parent_id, []).append(int(item["id"]))

        root_department = by_id.get(root_department_id)
        if not root_department:
            root_department = {"id": root_department_id, "name": str(root_department_id), "parentid": None}
            by_id[root_department_id] = root_department

        tree = {
            "root_id": root_department_id,
            "by_id": by_id,
            "children": children,
        }
        self._department_tree_cache[cache_key] = tree
        return tree

    def _department_path_segments(self, department_id: int, tree: Dict[str, Any]) -> List[str]:
        by_id = tree["by_id"]
        root_id = int(tree["root_id"])
        current_id = int(department_id)
        segments: List[str] = []
        seen = set()
        while current_id in by_id and current_id not in seen:
            seen.add(current_id)
            item = by_id[current_id]
            segments.append(item.get("name") or str(current_id))
            if current_id == root_id:
                break
            parent_id = item.get("parentid")
            if parent_id is None:
                break
            current_id = int(parent_id)
        segments.reverse()
        if segments and segments[0] == (by_id[root_id].get("name") or str(root_id)):
            return segments[1:]
        return segments

    @staticmethod
    def _normalize_name(name: str) -> str:
        return re.sub(r"\s+", "", name).casefold()

    def _build_visible_user_index(self, department_id: Optional[int]) -> Dict[str, Any]:
        cache_key = str(department_id) if department_id is not None else "visible"
        cached = self._directory_cache.get(cache_key)
        if cached:
            return cached

        departments = self.list_departments(department_id=department_id)
        if departments:
            department_ids = sorted({int(item["id"]) for item in departments if item.get("id") is not None})
        elif department_id is not None:
            department_ids = [department_id]
        else:
            department_ids = [1]

        department_name_map = {
            int(item["id"]): item.get("name")
            for item in departments
            if item.get("id") is not None
        }
        users_by_userid: Dict[str, Dict[str, Any]] = {}

        for current_department_id in department_ids:
            for item in self.list_department_users(current_department_id):
                userid = item.get("userid")
                if not userid:
                    continue
                entry = users_by_userid.setdefault(
                    userid,
                    {
                        "userid": userid,
                        "name": item.get("name"),
                        "department_ids": [],
                    },
                )
                for dept_id in item.get("department") or [current_department_id]:
                    if dept_id not in entry["department_ids"]:
                        entry["department_ids"].append(dept_id)

        name_index: Dict[str, List[Dict[str, Any]]] = {}
        for entry in users_by_userid.values():
            normalized = self._normalize_name(entry.get("name") or "")
            if not normalized:
                continue
            entry["department_names"] = [
                department_name_map.get(dept_id, str(dept_id))
                for dept_id in entry["department_ids"]
            ]
            name_index.setdefault(normalized, []).append(entry)

        directory = {
            "department_ids": department_ids,
            "department_count": len(department_ids),
            "user_count": len(users_by_userid),
            "name_index": name_index,
        }
        self._directory_cache[cache_key] = directory
        return directory

    def resolve_user_by_name(self, name: str, department_id: Optional[int] = None) -> Dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise SystemExit("按姓名解析时，姓名不能为空。")

        directory = self._build_visible_user_index(department_id=department_id)
        matches = directory["name_index"].get(self._normalize_name(clean_name), [])
        match_summary = [
            {
                "userid": item["userid"],
                "name": item.get("name"),
                "department_ids": item.get("department_ids") or [],
                "department_names": item.get("department_names") or [],
            }
            for item in matches
        ]

        self.audit.append(
            "user.resolve.name",
            {
                "lookup_mode": "name",
                "lookup_value": clean_name,
                "department_id": department_id,
                "searched_department_count": directory["department_count"],
                "searched_user_count": directory["user_count"],
                "match_count": len(matches),
                "matches": match_summary,
            },
        )

        if not matches:
            scope_hint = f"部门 {department_id}" if department_id is not None else "当前应用可见范围"
            raise SystemExit(
                f"未在{scope_hint}内找到姓名精确匹配的企业微信成员：{clean_name}。"
                " 请确认应用可见范围、通讯录权限，或改用 userid / 手机号 / 邮箱。"
            )
        if len(matches) > 1:
            candidates = "；".join(
                f"{item['userid']}（{'/'.join(item.get('department_names') or [str(x) for x in item.get('department_ids') or []])}）"
                for item in matches
            )
            raise SystemExit(
                f"姓名解析出现重名，无法自动判断：{clean_name}。候选项：{candidates}。"
                " 请改用 userid / 手机号 / 邮箱，或通过 --name-department-id 缩小部门范围。"
            )

        resolved_userid = matches[0]["userid"]
        detail = self._request(
            "GET",
            "/user/get",
            params=self._authed_params(userid=resolved_userid),
            audit_event="user.resolve.detail",
            audit_detail={"lookup_mode": "name", "resolved_userid": resolved_userid},
        )
        return {
            "lookup_mode": "name",
            "lookup_value": clean_name,
            "userid": detail.get("userid"),
            "name": detail.get("name"),
            "department": detail.get("department"),
            "status": detail.get("status"),
            "raw": detail,
        }

    def resolve_department_by_name(self, name: str, parent_department_id: Optional[int] = None) -> Dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise SystemExit("Department name must not be empty.")

        departments = self.list_departments(department_id=parent_department_id)
        matches = [
            item
            for item in departments
            if self._normalize_name(item.get("name") or "") == self._normalize_name(clean_name)
        ]
        match_summary = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "parentid": item.get("parentid"),
                "order": item.get("order"),
            }
            for item in matches
        ]
        self.audit.append(
            "department.resolve",
            {
                "lookup_mode": "name",
                "lookup_value": clean_name,
                "parent_department_id": parent_department_id,
                "match_count": len(matches),
                "matches": match_summary,
            },
        )

        if not matches:
            scope_hint = (
                f" under parent department {parent_department_id}"
                if parent_department_id is not None
                else ""
            )
            raise SystemExit(
                f'Unable to find an exact-matched department named "{clean_name}"{scope_hint}. '
                "Use --attendee-department-id if the department name is ambiguous."
            )
        if len(matches) > 1:
            candidates = ", ".join(
                f'{item.get("id")}:{item.get("name")}@{item.get("parentid")}' for item in matches
            )
            raise SystemExit(
                f'Ambiguous department name "{clean_name}". Candidates: {candidates}. '
                "Use --attendee-department-id to choose the target department."
            )
        return matches[0]

    def resolve_department_path(
        self,
        path_segments: List[str],
        *,
        root_department_id: int,
    ) -> Dict[str, Any]:
        if not path_segments:
            raise SystemExit("Department path must not be empty.")

        current_parent_id = root_department_id
        resolved_path: List[Dict[str, Any]] = []
        for segment in path_segments:
            subtree = self.list_departments(department_id=current_parent_id)
            matches = [
                item
                for item in subtree
                if int(item.get("parentid", -1)) == int(current_parent_id)
                and self._normalize_name(item.get("name") or "") == self._normalize_name(segment)
            ]
            self.audit.append(
                "department.resolve.path.segment",
                {
                    "segment": segment,
                    "parent_department_id": current_parent_id,
                    "match_count": len(matches),
                    "matches": [
                        {
                            "id": item.get("id"),
                            "name": item.get("name"),
                            "parentid": item.get("parentid"),
                        }
                        for item in matches
                    ],
                },
            )
            if not matches:
                path_text = " / ".join(path_segments)
                raise SystemExit(
                    f'Unable to resolve department path "{path_text}". '
                    f'No direct child named "{segment}" was found under department {current_parent_id}.'
                )
            if len(matches) > 1:
                candidates = ", ".join(
                    f'{item.get("id")}:{item.get("name")}@{item.get("parentid")}' for item in matches
                )
                raise SystemExit(
                    f'Ambiguous department path segment "{segment}" under department {current_parent_id}. '
                    f"Candidates: {candidates}. Use --attendee-department-id to choose directly."
                )
            resolved = matches[0]
            resolved_path.append(
                {
                    "id": resolved.get("id"),
                    "name": resolved.get("name"),
                    "parentid": resolved.get("parentid"),
                }
            )
            current_parent_id = int(resolved["id"])

        self.audit.append(
            "department.resolve.path",
            {
                "root_department_id": root_department_id,
                "path_segments": path_segments,
                "resolved_path": resolved_path,
            },
        )
        return matches[0]

    def search_department_candidates(
        self,
        query: str,
        *,
        root_department_id: int,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        clean_query = (query or "").strip()
        if not clean_query:
            return []

        tree = self._build_department_tree(root_department_id)
        normalized_query = self._normalize_name(clean_query)
        candidates: List[Dict[str, Any]] = []

        for department_id, item in tree["by_id"].items():
            if int(department_id) == int(root_department_id):
                continue
            path_segments = self._department_path_segments(int(department_id), tree)
            if not path_segments:
                continue
            path_text = "/".join(path_segments)
            normalized_path = self._normalize_name("".join(path_segments))
            normalized_name = self._normalize_name(item.get("name") or "")
            score = difflib.SequenceMatcher(None, normalized_query, normalized_path).ratio()
            if normalized_query and normalized_query in normalized_path:
                score += 0.25
            if normalized_query and normalized_query in normalized_name:
                score += 0.2
            score += 0.1 * difflib.SequenceMatcher(None, normalized_query, normalized_name).ratio()
            candidates.append(
                {
                    "department": {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "parentid": item.get("parentid"),
                    },
                    "path_segments": path_segments,
                    "path_text": path_text,
                    "score": round(score, 4),
                }
            )

        candidates.sort(key=lambda item: (-item["score"], len(item["path_segments"]), item["path_text"]))
        best = candidates[:limit]
        self.audit.append(
            "department.search",
            {
                "query": clean_query,
                "root_department_id": root_department_id,
                "candidate_count": len(best),
                "candidates": best,
            },
        )
        return best

    def resolve_department_by_query(
        self,
        query: str,
        *,
        root_department_id: int,
    ) -> Dict[str, Any]:
        candidates = self.search_department_candidates(
            query,
            root_department_id=root_department_id,
            limit=5,
        )
        if not candidates:
            raise SystemExit(
                f'Unable to find any department candidate for "{query}". '
                "Provide a clearer organization phrase or use an explicit department path."
            )

        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        top_score = float(top["score"])
        second_score = float(second["score"]) if second else 0.0
        if top_score < 0.72 or (second and top_score - second_score < 0.08):
            candidate_text = "; ".join(
                f'{item["path_text"]} (score={item["score"]})' for item in candidates[:3]
            )
            raise SystemExit(
                f'Department query "{query}" is ambiguous. Top candidates: {candidate_text}. '
                "Use --attendee-department-path or confirm the intended organization."
            )
        resolved = dict(top["department"])
        resolved["path_text"] = top["path_text"]
        resolved["match_score"] = top["score"]
        return resolved

    def resolve_department(
        self,
        *,
        department_id: Optional[int],
        department_name: Optional[str],
        department_path: Optional[List[str]],
        department_query: Optional[str],
        parent_department_id: Optional[int],
        root_department_id: int,
    ) -> Dict[str, Any]:
        if department_id is not None:
            departments = self.list_departments(department_id=department_id)
            return next(
                (
                    item
                    for item in departments
                    if int(item.get("id")) == int(department_id)
                ),
                {"id": department_id, "name": str(department_id), "parentid": parent_department_id},
            )
        if department_path:
            return self.resolve_department_path(
                department_path,
                root_department_id=root_department_id,
            )
        if department_name:
            return self.resolve_department_by_name(
                name=department_name,
                parent_department_id=parent_department_id,
            )
        if department_query:
            return self.resolve_department_by_query(
                department_query,
                root_department_id=root_department_id,
            )
        raise SystemExit(
            "Provide --attendee-department-id, --attendee-department-name, --attendee-department-path, or --attendee-department-query."
        )

    def preview_department_attendees(
        self,
        *,
        department_id: Optional[int],
        department_name: Optional[str],
        department_path: Optional[List[str]],
        department_query: Optional[str],
        include_child: bool,
        parent_department_id: Optional[int],
        root_department_id: int,
        preview_limit: int,
    ) -> Dict[str, Any]:
        resolved_department = self.resolve_department(
            department_id=department_id,
            department_name=department_name,
            department_path=department_path,
            department_query=department_query,
            parent_department_id=parent_department_id,
            root_department_id=root_department_id,
        )
        resolved_department_id = int(resolved_department["id"])

        users = self.list_department_users(
            resolved_department_id,
            fetch_child=1 if include_child else 0,
        )
        attendees: List[Dict[str, str]] = []
        sample_users: List[Dict[str, Any]] = []
        seen_userids = set()
        for item in users:
            userid = item.get("userid")
            if not userid or userid in seen_userids:
                continue
            attendees.append({"userid": userid})
            if len(sample_users) < preview_limit:
                sample_users.append(
                    {
                        "userid": userid,
                        "name": item.get("name"),
                        "department": item.get("department"),
                    }
                )
            seen_userids.add(userid)

        self.audit.append(
            "attendees.resolve.department",
            {
                "department": {
                    "id": resolved_department.get("id"),
                    "name": resolved_department.get("name"),
                    "parentid": resolved_department.get("parentid"),
                },
                "include_child": include_child,
                "attendee_count": len(attendees),
                "attendees": attendees,
            },
        )
        return {
            "department": {
                "id": resolved_department.get("id"),
                "name": resolved_department.get("name"),
                "parentid": resolved_department.get("parentid"),
            },
            "attendees": attendees,
            "attendee_count": len(attendees),
            "sample_users": sample_users,
            "preview_limit": preview_limit,
            "include_child": include_child,
        }

    def resolve_user(
        self,
        *,
        user_id: Optional[str],
        mobile: Optional[str],
        email: Optional[str],
        name: Optional[str],
        name_department_id: Optional[int],
    ) -> Dict[str, Any]:
        if user_id:
            detail = self._request(
                "GET",
                "/user/get",
                params=self._authed_params(userid=user_id),
                audit_event="user.resolve",
                audit_detail={"lookup_mode": "userid", "lookup_value": user_id},
            )
            return {
                "lookup_mode": "userid",
                "lookup_value": user_id,
                "userid": detail.get("userid"),
                "name": detail.get("name"),
                "department": detail.get("department"),
                "status": detail.get("status"),
                "raw": detail,
            }
        if mobile:
            payload = self._request(
                "POST",
                "/user/getuserid",
                params=self._authed_params(),
                json_body={"mobile": mobile},
                audit_event="user.resolve",
                audit_detail={"lookup_mode": "mobile", "lookup_value": mobile},
            )
            resolved_userid = payload.get("userid")
            detail = self._request(
                "GET",
                "/user/get",
                params=self._authed_params(userid=resolved_userid),
                audit_event="user.resolve.detail",
                audit_detail={"lookup_mode": "mobile", "resolved_userid": resolved_userid},
            )
            return {
                "lookup_mode": "mobile",
                "lookup_value": mobile,
                "userid": detail.get("userid"),
                "name": detail.get("name"),
                "department": detail.get("department"),
                "status": detail.get("status"),
                "raw": detail,
            }
        if email:
            payload = self._request(
                "POST",
                "/user/get_userid_by_email",
                params=self._authed_params(),
                json_body={"email": email},
                audit_event="user.resolve",
                audit_detail={"lookup_mode": "email", "lookup_value": email},
            )
            resolved_userid = payload.get("userid")
            detail = self._request(
                "GET",
                "/user/get",
                params=self._authed_params(userid=resolved_userid),
                audit_event="user.resolve.detail",
                audit_detail={"lookup_mode": "email", "resolved_userid": resolved_userid},
            )
            return {
                "lookup_mode": "email",
                "lookup_value": email,
                "userid": detail.get("userid"),
                "name": detail.get("name"),
                "department": detail.get("department"),
                "status": detail.get("status"),
                "raw": detail,
            }
        if name:
            return self.resolve_user_by_name(name=name, department_id=name_department_id)
        raise SystemExit("请至少提供一种用户标识：--user-id、--mobile、--email 或 --name，以便完成可审计的用户解析。")

    def create_calendar(
        self,
        *,
        summary: str,
        description: str,
        admins: List[str],
        shares: List[Dict[str, str]],
        color: str,
        set_as_default: int,
        is_public: int,
        public_range: Optional[Dict[str, Any]],
        is_corp_calendar: int,
    ) -> Dict[str, Any]:
        body = {
            "agentid": self.agent_id,
            "calendar": compact_payload(
                {
                    "admins": admins,
                    "summary": summary,
                    "description": description,
                    "color": color,
                    "shares": shares,
                    "set_as_default": set_as_default,
                    "is_public": is_public,
                    "public_range": public_range,
                    "is_corp_calendar": is_corp_calendar,
                }
            ),
        }
        return self._request(
            "POST",
            "/oa/calendar/add",
            params=self._authed_params(),
            json_body=body,
            audit_event="calendar.create",
        )

    def create_schedule(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/oa/schedule/add",
            params=self._authed_params(),
            json_body=body,
            audit_event="schedule.create",
        )

    def update_schedule(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/oa/schedule/update",
            params=self._authed_params(),
            json_body=body,
            audit_event="schedule.update",
        )

    def get_schedule(self, schedule_ids: List[str]) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/oa/schedule/get",
            params=self._authed_params(),
            json_body={"schedule_id_list": schedule_ids},
            audit_event="schedule.get",
            audit_detail={"schedule_id_list": schedule_ids},
        )

    def list_calendar_schedules(self, cal_id: str, offset: int, limit: int) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/oa/schedule/get_by_calendar",
            params=self._authed_params(),
            json_body={"cal_id": cal_id, "offset": offset, "limit": limit},
            audit_event="schedule.list",
        )

    def cancel_schedule(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/oa/schedule/del",
            params=self._authed_params(),
            json_body=body,
            audit_event="schedule.cancel",
        )

    def add_attendees(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/oa/schedule/add_attendees",
            params=self._authed_params(),
            json_body=body,
            audit_event="schedule.add_attendees",
        )

    def del_attendees(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/oa/schedule/del_attendees",
            params=self._authed_params(),
            json_body=body,
            audit_event="schedule.del_attendees",
        )

    def send_text_message(self, touser: str, content: str) -> Dict[str, Any]:
        body = {
            "touser": touser,
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": content},
            "safe": 0,
            "enable_id_trans": 0,
            "enable_duplicate_check": 1,
        }
        return self._request(
            "POST",
            "/message/send",
            params=self._authed_params(),
            json_body=body,
            audit_event="reminder.send",
        )

    def create_meeting(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/meeting/create",
            params=self._authed_params(),
            json_body=body,
            audit_event="meeting.create",
        )


def parse_attendees(attendees_json: Optional[str], default_userid: Optional[str]) -> List[Dict[str, str]]:
    attendees = parse_json(attendees_json, [])
    if attendees:
        return attendees
    if default_userid:
        return [{"userid": default_userid}]
    return []


def parse_name_list(names_json: Optional[str]) -> List[str]:
    names = parse_json(names_json, [])
    if not names:
        return []
    if not isinstance(names, list):
        raise SystemExit("姓名列表必须是 JSON 数组，例如 [\"张三\", \"李四\"]。")
    normalized: List[str] = []
    for item in names:
        value = str(item).strip()
        if value:
            normalized.append(value)
    return normalized


def parse_department_path(path_value: Optional[str]) -> List[str]:
    if not path_value:
        return []
    segments = re.split(r"\s*(?:/|>|\\)\s*", path_value.strip())
    return [segment.strip() for segment in segments if segment.strip()]


def parse_userids(userids_csv: Optional[str]) -> List[str]:
    if not userids_csv:
        return []
    return [item.strip() for item in userids_csv.split(",") if item.strip()]


def normalize_attendees(attendees: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for attendee in attendees or []:
        userid = attendee.get("userid")
        if userid:
            normalized.append({"userid": userid})
    return normalized


def merge_attendees(
    *sources: Optional[List[Dict[str, Any]]],
    default_userid: Optional[str] = None,
) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen_userids = set()
    for source in sources:
        for attendee in normalize_attendees(source):
            userid = attendee["userid"]
            if userid in seen_userids:
                continue
            merged.append({"userid": userid})
            seen_userids.add(userid)
    if merged:
        return merged
    if default_userid:
        return [{"userid": default_userid}]
    return []


def normalize_reminders(reminders: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    source = reminders or {}
    if not source:
        return {"is_remind": 1, "remind_before_event_secs": 900, "is_repeat": 0}
    normalized = {
        "is_remind": source.get("is_remind", 1),
        "is_repeat": source.get("is_repeat", 0),
    }
    if normalized["is_remind"]:
        normalized["remind_before_event_secs"] = source.get("remind_before_event_secs", 900)
    return normalized


def build_department_query_assessment(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        return {"status": "not_found", "best": None, "second": None}
    best = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    best_score = float(best["score"])
    second_score = float(second["score"]) if second else 0.0
    if best_score < 0.72:
        return {"status": "low_confidence", "best": best, "second": second}
    if second and best_score - second_score < 0.08:
        return {"status": "ambiguous", "best": best, "second": second}
    return {"status": "ready", "best": best, "second": second}


def infer_schedule_copy(
    *,
    summary: Optional[str],
    description: Optional[str],
    location: Optional[str],
    department_resolution: Optional[Dict[str, Any]],
    attendee_count: int,
    start: Optional[str],
) -> Dict[str, Any]:
    summary_provided = bool((summary or "").strip())
    description_provided = bool((description or "").strip())
    department_name = None
    if department_resolution:
        department = department_resolution.get("department") or {}
        department_name = department.get("name")
    if not department_name and department_resolution:
        department_name = department_resolution.get("path_text")

    inferred_summary = (summary or "").strip()
    if not inferred_summary:
        date_hint = ""
        if start and len(start) >= 10:
            date_hint = start[:10]
        base = department_name or "相关团队"
        inferred_summary = f"{base}沟通日程"
        if location and "线上" in location:
            inferred_summary = f"{base}线上沟通"
        if date_hint:
            inferred_summary = f"{date_hint} {inferred_summary}"

    inferred_description = (description or "").strip()
    if not inferred_description:
        parts = ["系统根据当前请求自动生成的日程说明。"]
        if department_name:
            parts.append(f"目标组织：{department_name}。")
        if attendee_count:
            parts.append(f"预计参会人数：{attendee_count}。")
        if location:
            parts.append(f"地点：{location}。")
        inferred_description = " ".join(parts)

    return {
        "summary": inferred_summary,
        "description": inferred_description,
        "summary_inferred": not summary_provided,
        "description_inferred": not description_provided,
        "needs_copy_confirmation": (not summary_provided) or (not description_provided),
        "copy_follow_up": (
            "是否需要我进一步拟定更准确的会议主题和会议内容？"
            if (not summary_provided) or (not description_provided)
            else None
        ),
    }


def apply_request_file(args: argparse.Namespace) -> argparse.Namespace:
    payload = None
    if args.request_file:
        payload = json.loads(Path(args.request_file).read_text(encoding="utf-8-sig"))
    elif args.request_stdin:
        payload = json.loads(read_stdin_json_text())
    if payload is None:
        return args
    if "attendee_names" in payload and "attendee_names_json" not in payload:
        payload["attendee_names_json"] = payload["attendee_names"]
    if "attendee_department_path_json" in payload and "attendee_department_path" not in payload:
        path_value = payload["attendee_department_path_json"]
        if isinstance(path_value, list):
            payload["attendee_department_path"] = "/".join(str(item).strip() for item in path_value if str(item).strip())
    for key, value in payload.items():
        if not hasattr(args, key):
            continue
        current = getattr(args, key)
        if current in (None, ""):
            if key.endswith("_json") and not isinstance(value, str):
                setattr(args, key, json.dumps(value, ensure_ascii=False))
            else:
                setattr(args, key, value)
    return args


def apply_text_file_inputs(args: argparse.Namespace) -> argparse.Namespace:
    file_map = {
        "summary_file": "summary",
        "description_file": "description",
        "location_file": "location",
        "content_file": "content",
    }
    for source_attr, target_attr in file_map.items():
        source_path = getattr(args, source_attr, None)
        if source_path:
            setattr(args, target_attr, read_utf8_text(source_path))

    json_file_map = {
        "attendees_file": "attendees_json",
        "attendee_names_file": "attendee_names_json",
        "shares_file": "shares_json",
        "public_range_file": "public_range_json",
        "reminders_file": "reminders_json",
    }
    for source_attr, target_attr in json_file_map.items():
        source_path = getattr(args, source_attr, None)
        if source_path:
            setattr(args, target_attr, read_utf8_json_text(source_path))
    return args


def filter_schedule_item(
    schedule: Dict[str, Any],
    *,
    attendee_userid: Optional[str],
    start_time: Optional[int],
    end_time: Optional[int],
) -> bool:
    if attendee_userid:
        attendees = schedule.get("attendees") or []
        if not any(item.get("userid") == attendee_userid for item in attendees):
            return False
    if start_time and schedule.get("end_time", 0) < start_time:
        return False
    if end_time and schedule.get("start_time", 0) > end_time:
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通过可审计的命令行方式管理企业微信日程。"
    )
    parser.add_argument(
        "action",
        choices=[
            "resolve-user",
            "create-calendar",
            "list-schedules",
            "get-schedule",
            "prepare-schedule-create",
            "preview-department-attendees",
            "create-schedule",
            "create-meeting",
            "update-schedule",
            "cancel-schedule",
            "add-attendees",
            "del-attendees",
            "send-reminder",
        ],
    )
    parser.add_argument("--channel", default="wecom", help="固定为 wecom。")
    parser.add_argument("--corp-id")
    parser.add_argument("--corp-secret")
    parser.add_argument("--agent-id")
    parser.add_argument("--cal-id")
    parser.add_argument(
        "--calendar-bindings-path",
        default=os.getenv("WECOM_CALENDAR_BINDINGS_PATH", "logs/wecom_calendar_bindings.json"),
        help="用户与 cal_id 的本地绑定文件，首次自动建日历后会写入这里。",
    )
    parser.add_argument("--operator-id", help="写入审计日志的操作者标识。")
    parser.add_argument("--audit-log-path", default=os.getenv("WECOM_AUDIT_LOG_PATH", "logs/wecom_audit.jsonl"))
    parser.add_argument("--request-id", default=None)
    parser.add_argument(
        "--request-file",
        help="包含请求字段的 UTF-8 JSON 文件，适合避免终端编码问题。",
    )
    parser.add_argument(
        "--request-stdin",
        action="store_true",
        help="从标准输入读取 UTF-8 JSON 请求对象。",
    )

    parser.add_argument("--user-id", help="企业微信 userid。")
    parser.add_argument("--mobile", help="用于解析 userid 的手机号。")
    parser.add_argument("--email", help="用于解析 userid 的邮箱地址。")
    parser.add_argument("--name", help="用于精确解析 userid 的姓名。")
    parser.add_argument(
        "--name-department-id",
        type=int,
        help="按姓名解析时可选，用于缩小搜索范围的部门 ID。",
    )

    parser.add_argument("--summary")
    parser.add_argument("--description")
    parser.add_argument("--location")
    parser.add_argument("--summary-file", help="标题对应的 UTF-8 文本文件。")
    parser.add_argument("--description-file", help="描述对应的 UTF-8 文本文件。")
    parser.add_argument("--location-file", help="地点对应的 UTF-8 文本文件。")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--schedule-id")
    parser.add_argument("--schedule-ids", help="用于 get-schedule 的多个日程 ID，逗号分隔。")
    parser.add_argument("--touser", help="提醒消息接收人，例如 user1|user2")
    parser.add_argument("--content", help="提醒消息正文。")
    parser.add_argument("--content-file", help="提醒消息正文对应的 UTF-8 文本文件。")

    parser.add_argument("--admins", help="日历管理员 userid，逗号分隔。")
    parser.add_argument("--shares-json", help='共享对象 JSON 列表，例如 [{"userid":"alice"}]。')
    parser.add_argument("--attendees-json", help='参会人 JSON 列表，例如 [{"userid":"alice"}]。')
    parser.add_argument("--attendee-names-json", help='参会人姓名 JSON 列表，例如 ["张三","李四"]。')
    parser.add_argument("--attendee-department-id", type=int, help="参会部门 ID，用于批量添加部门成员。")
    parser.add_argument("--attendee-department-name", help="参会部门名称，按精确名称匹配后批量添加部门成员。")
    parser.add_argument("--attendee-department-path", help="参会部门路径，例如 一级组织/二级团队。")
    parser.add_argument("--attendee-department-query", help="参会组织自然语言短语，例如 一级组织二级团队，脚本会自动遍历组织树推断路径。")
    parser.add_argument(
        "--attendee-department-parent-id",
        type=int,
        help="按部门名称解析时可选，用于限制在某个父部门下匹配。",
    )
    parser.add_argument(
        "--attendee-department-root-id",
        type=int,
        default=None,
        help="按部门路径解析时的根部门 ID，默认读取 WECOM_DEPARTMENT_ROOT_ID，未配置时使用 1。",
    )
    parser.add_argument(
        "--attendee-direct-only",
        action="store_true",
        help="只添加目标部门直属成员，不展开子部门成员。",
    )
    parser.add_argument("--preview-limit", type=int, default=5, help="预览部门成员时返回的样本人数。")
    parser.add_argument("--public-range-json", help="public_range 对应的 JSON 对象。")
    parser.add_argument("--shares-file", help="共享对象对应的 UTF-8 JSON 文件。")
    parser.add_argument("--attendees-file", help="参会人对应的 UTF-8 JSON 文件。")
    parser.add_argument("--attendee-names-file", help="参会人姓名对应的 UTF-8 JSON 文件。")
    parser.add_argument("--public-range-file", help="public_range 对应的 UTF-8 JSON 文件。")
    parser.add_argument("--color", default="#FF3030")
    parser.add_argument("--set-as-default", type=int, default=0)
    parser.add_argument("--is-public", type=int, default=0)
    parser.add_argument("--is-corp-calendar", type=int, default=0)
    parser.add_argument("--auto-create-calendar", action="store_true")

    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--attendee-userid", help="按参会人 userid 过滤查询结果。")

    parser.add_argument("--skip-attendees", type=int, default=0)
    parser.add_argument("--op-mode", type=int, default=0)
    parser.add_argument("--op-start-time", type=int, default=None)
    parser.add_argument("--reminders-json", help="原始 reminders JSON。")
    parser.add_argument("--reminders-file", help="reminders 对应的 UTF-8 JSON 文件。")
    parser.add_argument("--meeting-settings-json", help="创建会议时透传的会议设置 JSON。")
    return parser


def require_cal_id(args: argparse.Namespace) -> str:
    cal_id = env_or_value(args.cal_id, "WECOM_CAL_ID", required=False)
    if not cal_id:
        raise SystemExit("缺少日历 ID。请传入 --cal-id 或设置环境变量 WECOM_CAL_ID。")
    return cal_id


def build_client(args: argparse.Namespace) -> WeComClient:
    channel = args.channel
    ensure_wecom_channel(channel)
    audit = AuditContext(
        path=Path(args.audit_log_path),
        request_id=args.request_id or str(uuid.uuid4()),
        channel=channel,
        operator_id=args.operator_id,
    )
    corp_id = env_or_value(args.corp_id, "WECOM_CORP_ID", required=True)
    corp_secret = env_or_value(args.corp_secret, "WECOM_CORP_SECRET", required=True)
    agent_id = env_or_value(args.agent_id, "WECOM_AGENT_ID", required=True)
    return WeComClient(corp_id=corp_id, corp_secret=corp_secret, agent_id=agent_id, audit=audit)


def build_calendar_binding_store(args: argparse.Namespace) -> CalendarBindingStore:
    return CalendarBindingStore(Path(args.calendar_bindings_path))


def resolve_name_department_id(args: argparse.Namespace) -> Optional[int]:
    value = args.name_department_id
    if value is not None:
        return value
    env_value = os.getenv("WECOM_NAME_DEPARTMENT_ID")
    if not env_value:
        return None
    return int(env_value)


def resolve_department_root_id(args: argparse.Namespace) -> int:
    if args.attendee_department_root_id is not None:
        return int(args.attendee_department_root_id)
    env_value = os.getenv("WECOM_DEPARTMENT_ROOT_ID")
    if env_value:
        return int(env_value)
    return 1


def resolve_primary_user(client: WeComClient, args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if args.user_id or args.mobile or args.email or args.name:
        return client.resolve_user(
            user_id=args.user_id,
            mobile=args.mobile,
            email=args.email,
            name=args.name,
            name_department_id=resolve_name_department_id(args),
        )
    return None


def resolve_attendees_from_names(
    client: WeComClient,
    attendee_names_json: Optional[str],
    *,
    name_department_id: Optional[int],
) -> List[Dict[str, str]]:
    names = parse_name_list(attendee_names_json)
    if not names:
        return []
    resolved_attendees: List[Dict[str, str]] = []
    seen_userids = set()
    for name in names:
        resolved = client.resolve_user(
            user_id=None,
            mobile=None,
            email=None,
            name=name,
            name_department_id=name_department_id,
        )
        userid = resolved["userid"]
        if userid not in seen_userids:
            resolved_attendees.append({"userid": userid})
            seen_userids.add(userid)
    return resolved_attendees


def resolve_attendees_from_department(args: argparse.Namespace, client: WeComClient) -> Dict[str, Any]:
    has_department_selector = any(
        [
            args.attendee_department_id is not None,
            bool(args.attendee_department_name),
            bool(args.attendee_department_path),
            bool(args.attendee_department_query),
        ]
    )
    if not has_department_selector:
        return {
            "department": None,
            "attendees": [],
            "attendee_count": 0,
            "sample_users": [],
            "preview_limit": args.preview_limit,
            "include_child": not args.attendee_direct_only,
        }
    return client.preview_department_attendees(
        department_id=args.attendee_department_id,
        department_name=args.attendee_department_name,
        department_path=parse_department_path(args.attendee_department_path),
        department_query=args.attendee_department_query,
        include_child=not args.attendee_direct_only,
        parent_department_id=args.attendee_department_parent_id,
        root_department_id=resolve_department_root_id(args),
        preview_limit=args.preview_limit,
    )


def maybe_auto_create_calendar(
    client: WeComClient,
    args: argparse.Namespace,
    resolved_user: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not args.auto_create_calendar:
        return None
    if env_or_value(args.cal_id, "WECOM_CAL_ID", required=False):
        return None
    user_id = (resolved_user or {}).get("userid")
    if not user_id:
        raise SystemExit("--auto-create-calendar 需要先通过 --user-id、--mobile、--email 或 --name 解析出有效用户。")
    admins = parse_userids(args.admins) or [user_id]
    shares = parse_json(args.shares_json, [{"userid": user_id}])
    summary = args.summary or f"{user_id} 自动创建日历"
    description = args.description or "Created by WeCom schedule manager skill."
    public_range = parse_json(args.public_range_json, None)
    return client.create_calendar(
        summary=summary,
        description=description,
        admins=admins,
        shares=shares,
        color=args.color,
        set_as_default=args.set_as_default,
        is_public=args.is_public,
        public_range=public_range,
        is_corp_calendar=args.is_corp_calendar,
    )


def resolve_effective_calendar(
    client: WeComClient,
    args: argparse.Namespace,
    resolved_user: Optional[Dict[str, Any]],
    binding_store: CalendarBindingStore,
) -> Dict[str, Any]:
    explicit_cal_id = env_or_value(args.cal_id, "WECOM_CAL_ID", required=False)
    user_id = (resolved_user or {}).get("userid")
    binding_record = None
    if user_id:
        binding_record = binding_store.get(
            corp_id=client.corp_id,
            agent_id=str(client.agent_id),
            user_id=user_id,
        )
        client.audit.append(
            "calendar.binding.lookup",
            {
                "user_id": user_id,
                "binding_found": bool(binding_record),
                "bindings_path": str(binding_store.path),
                "bound_cal_id": (binding_record or {}).get("cal_id"),
            },
        )

    if explicit_cal_id:
        return {
            "effective_cal_id": explicit_cal_id,
            "source": "explicit",
            "binding_record": binding_record,
            "auto_calendar": None,
        }

    if binding_record and binding_record.get("cal_id"):
        return {
            "effective_cal_id": binding_record["cal_id"],
            "source": "binding",
            "binding_record": binding_record,
            "auto_calendar": None,
        }

    should_auto_create = args.auto_create_calendar or args.action == "create-schedule"
    if should_auto_create and user_id:
        auto_calendar = maybe_auto_create_calendar(client, args, resolved_user) or client.create_calendar(
            summary=args.summary or f"{user_id} 自动创建日历",
            description=args.description or "Created by WeCom schedule manager skill.",
            admins=parse_userids(args.admins) or [user_id],
            shares=parse_json(args.shares_json, [{"userid": user_id}]),
            color=args.color,
            set_as_default=args.set_as_default,
            is_public=args.is_public,
            public_range=parse_json(args.public_range_json, None),
            is_corp_calendar=args.is_corp_calendar,
        )
        cal_id = auto_calendar.get("cal_id")
        if cal_id:
            binding_record = binding_store.set(
                corp_id=client.corp_id,
                agent_id=str(client.agent_id),
                user_id=user_id,
                user_name=(resolved_user or {}).get("name"),
                cal_id=cal_id,
                source="auto_created",
            )
            client.audit.append(
                "calendar.binding.write",
                {
                    "user_id": user_id,
                    "cal_id": cal_id,
                    "source": "auto_created",
                    "bindings_path": str(binding_store.path),
                },
            )
        return {
            "effective_cal_id": cal_id,
            "source": "auto_created",
            "binding_record": binding_record,
            "auto_calendar": auto_calendar,
        }

    return {
        "effective_cal_id": None,
        "source": "missing",
        "binding_record": binding_record,
        "auto_calendar": None,
    }


def merged_update_schedule(
    current: Dict[str, Any],
    args: argparse.Namespace,
    explicit_attendees: Optional[List[Dict[str, str]]],
) -> Dict[str, Any]:
    if args.skip_attendees:
        attendees = normalize_attendees(current.get("attendees"))
    elif explicit_attendees:
        attendees = normalize_attendees(explicit_attendees)
    else:
        attendees = normalize_attendees(current.get("attendees"))

    schedule = {
        "schedule_id": current["schedule_id"],
        "start_time": parse_time(args.start) if args.start else current.get("start_time"),
        "end_time": parse_time(args.end) if args.end else current.get("end_time"),
        "summary": args.summary if args.summary is not None else current.get("summary"),
        "description": args.description if args.description is not None else current.get("description"),
        "location": args.location if args.location is not None else current.get("location"),
        "attendees": attendees,
        "reminders": normalize_reminders(parse_json(args.reminders_json, current.get("reminders"))),
    }
    if current.get("cal_id"):
        schedule["cal_id"] = current.get("cal_id")
    return compact_payload(
        {
            "schedule": schedule,
        }
    )


def build_department_candidate_preview(
    client: WeComClient,
    *,
    department_id: int,
    include_child: bool,
    root_department_id: int,
    preview_limit: int,
) -> Dict[str, Any]:
    return client.preview_department_attendees(
        department_id=department_id,
        department_name=None,
        department_path=None,
        department_query=None,
        include_child=include_child,
        parent_department_id=None,
        root_department_id=root_department_id,
        preview_limit=preview_limit,
    )


def prepare_schedule_create(
    client: WeComClient,
    args: argparse.Namespace,
    resolved_user: Optional[Dict[str, Any]],
    binding_store: CalendarBindingStore,
    resolved_name_attendees: List[Dict[str, str]],
) -> Dict[str, Any]:
    calendar_context = resolve_effective_calendar(client, args, resolved_user, binding_store)
    root_department_id = resolve_department_root_id(args)
    department_resolution: Dict[str, Any]
    if args.attendee_department_query:
        candidates = client.search_department_candidates(
            args.attendee_department_query,
            root_department_id=root_department_id,
            limit=3,
        )
        assessment = build_department_query_assessment(candidates)
        if assessment["status"] != "ready":
            candidate_previews = []
            for item in candidates[:3]:
                preview = build_department_candidate_preview(
                    client,
                    department_id=int(item["department"]["id"]),
                    include_child=not args.attendee_direct_only,
                    root_department_id=root_department_id,
                    preview_limit=args.preview_limit,
                )
                candidate_previews.append(
                    {
                        "department": preview["department"],
                        "path_text": item["path_text"],
                        "score": item["score"],
                        "attendee_count": preview["attendee_count"],
                        "sample_users": preview["sample_users"],
                    }
                )
            return {
                "request_id": client.audit.request_id,
                "channel": "wecom",
                "status": "needs_confirmation",
                "reason": f"department_query_{assessment['status']}",
                "resolved_user": resolved_user,
                "calendar_binding": calendar_context["binding_record"],
                "calendar_resolution": {
                    "source": calendar_context["source"],
                    "effective_cal_id": calendar_context["effective_cal_id"],
                    "bindings_path": str(binding_store.path),
                },
                "department_query": args.attendee_department_query,
                "candidate_departments": candidate_previews,
                "next_prompt": "请确认要使用哪个组织，确认后再创建完整日程。",
                "audit_log_path": str(client.audit.path),
            }
        department_resolution = build_department_candidate_preview(
            client,
            department_id=int(assessment["best"]["department"]["id"]),
            include_child=not args.attendee_direct_only,
            root_department_id=root_department_id,
            preview_limit=args.preview_limit,
        )
    else:
        department_resolution = resolve_attendees_from_department(args, client)

    user_id = (resolved_user or {}).get("userid")
    explicit_attendees = merge_attendees(
        parse_attendees(args.attendees_json, None),
        resolved_name_attendees,
        department_resolution["attendees"],
        default_userid=user_id,
    )
    inferred_copy = infer_schedule_copy(
        summary=args.summary,
        description=args.description,
        location=args.location,
        department_resolution=department_resolution,
        attendee_count=len(explicit_attendees),
        start=args.start,
    )
    return {
        "request_id": client.audit.request_id,
        "channel": "wecom",
        "status": "ready",
        "resolved_user": resolved_user,
        "effective_cal_id": calendar_context["effective_cal_id"],
        "calendar_binding": calendar_context["binding_record"],
        "calendar_resolution": {
            "source": calendar_context["source"],
            "effective_cal_id": calendar_context["effective_cal_id"],
            "bindings_path": str(binding_store.path),
            "will_auto_create_on_create": not bool(calendar_context["effective_cal_id"]) and bool(user_id),
        },
        "resolved_attendee_sources": {
            "names": resolved_name_attendees,
            "department": department_resolution,
        },
        "attendee_count": len(explicit_attendees),
        "sample_attendees": department_resolution.get("sample_users", [])[: args.preview_limit],
        "draft_schedule": {
            "summary": inferred_copy["summary"],
            "description": inferred_copy["description"],
            "location": args.location,
            "start": args.start,
            "end": args.end,
            "attendees": explicit_attendees,
        },
        "copy_suggestion": {
            "summary_inferred": inferred_copy["summary_inferred"],
            "description_inferred": inferred_copy["description_inferred"],
            "needs_confirmation": inferred_copy["needs_copy_confirmation"],
            "next_prompt": inferred_copy["copy_follow_up"],
        },
        "meeting_follow_up": {
            "default_create_meeting": False,
            "supported": True,
            "next_prompt": "是否需要在日程确认后继续创建会议？",
        },
        "audit_log_path": str(client.audit.path),
    }


def run_action(args: argparse.Namespace) -> Dict[str, Any]:
    client = build_client(args)
    binding_store = build_calendar_binding_store(args)
    resolved_user = resolve_primary_user(client, args)
    name_department_id = resolve_name_department_id(args)
    resolved_name_attendees = resolve_attendees_from_names(
        client,
        args.attendee_names_json,
        name_department_id=name_department_id,
    )
    if args.action == "prepare-schedule-create":
        return prepare_schedule_create(
            client,
            args,
            resolved_user,
            binding_store,
            resolved_name_attendees,
        )
    resolved_department_result = resolve_attendees_from_department(args, client)
    resolved_department_attendees = resolved_department_result["attendees"]
    explicit_attendees = merge_attendees(
        parse_attendees(args.attendees_json, None),
        resolved_name_attendees,
        resolved_department_attendees,
        default_userid=None,
    )
    calendar_context = resolve_effective_calendar(client, args, resolved_user, binding_store)
    effective_cal_id = calendar_context["effective_cal_id"]

    if args.action == "resolve-user":
        if not resolved_user:
            raise SystemExit("resolve-user 需要提供 --user-id、--mobile、--email 或 --name。")
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "resolved_user": resolved_user,
            "effective_cal_id": effective_cal_id,
            "calendar_binding": calendar_context["binding_record"],
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "create-calendar":
        if calendar_context["auto_calendar"]:
            calendar = calendar_context["auto_calendar"]
            binding_record = calendar_context["binding_record"]
        else:
            user_id = (resolved_user or {}).get("userid")
            admins = parse_userids(args.admins) or ([user_id] if user_id else [])
            shares = parse_json(args.shares_json, ([{"userid": user_id}] if user_id else []))
            calendar = client.create_calendar(
                summary=args.summary or "自动化日历",
                description=args.description or "Created by WeCom schedule manager skill.",
                admins=admins,
                shares=shares,
                color=args.color,
                set_as_default=args.set_as_default,
                is_public=args.is_public,
                public_range=parse_json(args.public_range_json, None),
                is_corp_calendar=args.is_corp_calendar,
            )
            binding_record = calendar_context["binding_record"]
            if user_id and calendar.get("cal_id"):
                binding_record = binding_store.set(
                    corp_id=client.corp_id,
                    agent_id=str(client.agent_id),
                    user_id=user_id,
                    user_name=(resolved_user or {}).get("name"),
                    cal_id=calendar["cal_id"],
                    source="create_calendar",
                )
                client.audit.append(
                    "calendar.binding.write",
                    {
                        "user_id": user_id,
                        "cal_id": calendar["cal_id"],
                        "source": "create_calendar",
                        "bindings_path": str(binding_store.path),
                    },
                )
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "calendar": calendar,
            "calendar_binding": binding_record if 'binding_record' in locals() else calendar_context["binding_record"],
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "list-schedules":
        cal_id = effective_cal_id or require_cal_id(args)
        start_time = parse_time(args.start) if args.start else None
        end_time = parse_time(args.end) if args.end else None
        schedule_list: List[Dict[str, Any]] = []
        offset = args.offset
        while True:
            page = client.list_calendar_schedules(cal_id, offset=offset, limit=args.limit)
            page_items = page.get("schedule_list") or []
            if not page_items:
                break
            schedule_list.extend(page_items)
            offset += args.limit
            if len(page_items) < args.limit:
                break
        if start_time or end_time or args.attendee_userid:
            schedule_list = [
                item
                for item in schedule_list
                if filter_schedule_item(
                    item,
                    attendee_userid=args.attendee_userid,
                    start_time=start_time,
                    end_time=end_time,
                )
            ]
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "cal_id": cal_id,
            "calendar_binding": calendar_context["binding_record"],
            "count": len(schedule_list),
            "schedules": schedule_list,
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "get-schedule":
        schedule_ids = parse_userids(args.schedule_ids)
        if args.schedule_id:
            schedule_ids.append(args.schedule_id)
        if not schedule_ids:
            raise SystemExit("get-schedule 需要提供 --schedule-id 或 --schedule-ids。")
        payload = client.get_schedule(schedule_ids)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "schedule_list": payload.get("schedule_list") or [],
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "preview-department-attendees":
        if not (
            args.attendee_department_id is not None
            or args.attendee_department_name
            or args.attendee_department_path
            or args.attendee_department_query
        ):
            raise SystemExit(
                "preview-department-attendees 需要提供 --attendee-department-id、"
                "--attendee-department-name、--attendee-department-path 或 --attendee-department-query。"
            )
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "resolved_department": resolved_department_result["department"],
            "attendee_count": resolved_department_result["attendee_count"],
            "sample_users": resolved_department_result["sample_users"],
            "preview_limit": resolved_department_result["preview_limit"],
            "include_child": resolved_department_result["include_child"],
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "create-schedule":
        user_id = (resolved_user or {}).get("userid")
        if not args.start or not args.end:
            raise SystemExit("create-schedule 需要提供 --start 和 --end。")
        attendees = merge_attendees(explicit_attendees, default_userid=user_id)
        schedule = {
            "start_time": parse_time(args.start),
            "end_time": parse_time(args.end),
            "attendees": attendees,
            "summary": args.summary,
            "description": args.description,
            "location": args.location,
            "reminders": parse_json(args.reminders_json, {"is_remind": 1, "remind_before_event_secs": 900, "is_repeat": 0}),
            "cal_id": effective_cal_id or require_cal_id(args),
        }
        body = {"schedule": compact_payload(schedule)}
        payload = client.create_schedule(body)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "resolved_user": resolved_user,
            "resolved_attendees": attendees,
            "resolved_attendee_sources": {
                "names": resolved_name_attendees,
                "department": resolved_department_result,
            },
            "created_schedule": payload,
            "effective_cal_id": schedule["cal_id"],
            "calendar_binding": calendar_context["binding_record"],
            "calendar_resolution": {
                "source": calendar_context["source"],
                "bindings_path": str(binding_store.path),
            },
            "meeting_follow_up": {
                "default_create_meeting": False,
                "supported": True,
                "next_prompt": "日程已创建，是否需要继续创建会议？",
            },
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "create-meeting":
        user_id = (resolved_user or {}).get("userid")
        if not user_id:
            raise SystemExit("create-meeting 需要先解析出会议管理员用户。")
        if not args.start or not args.end:
            raise SystemExit("create-meeting 需要提供 --start 和 --end。")
        attendees = merge_attendees(explicit_attendees, default_userid=user_id)
        start_ts = parse_time(args.start)
        end_ts = parse_time(args.end)
        duration_minutes = max(1, int((end_ts - start_ts) / 60))
        body = compact_payload(
            {
                "admin_userid": user_id,
                "title": args.summary or "企业微信会议",
                "meeting_start": start_ts,
                "meeting_duration": duration_minutes,
                "description": args.description,
                "location": args.location,
                "agentid": client.agent_id,
                "attendees": {"userid": [item["userid"] for item in attendees]},
                "settings": parse_json(args.meeting_settings_json, None),
            }
        )
        payload = client.create_meeting(body)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "resolved_user": resolved_user,
            "resolved_attendees": attendees,
            "meeting_request": body,
            "meeting_result": payload,
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "update-schedule":
        if not args.schedule_id:
            raise SystemExit("update-schedule 需要提供 --schedule-id。")
        current_payload = client.get_schedule([args.schedule_id])
        schedule_list = current_payload.get("schedule_list") or []
        if not schedule_list:
            raise SystemExit(f"未找到日程：{args.schedule_id}")
        body = merged_update_schedule(schedule_list[0], args, explicit_attendees)
        payload = client.update_schedule(body)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "updated_schedule": payload,
            "resolved_attendees": explicit_attendees,
            "resolved_attendee_sources": {
                "names": resolved_name_attendees,
                "department": resolved_department_result,
            },
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "cancel-schedule":
        if not args.schedule_id:
            raise SystemExit("cancel-schedule 需要提供 --schedule-id。")
        body = compact_payload(
            {
                "schedule_id": args.schedule_id,
                "op_mode": args.op_mode if args.op_mode else None,
                "op_start_time": args.op_start_time,
            }
        )
        payload = client.cancel_schedule(body)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "cancel_result": payload,
            "audit_log_path": str(client.audit.path),
        }

    if args.action in {"add-attendees", "del-attendees"}:
        if not args.schedule_id:
            raise SystemExit(f"{args.action} 需要提供 --schedule-id。")
        attendees = merge_attendees(explicit_attendees, default_userid=(resolved_user or {}).get("userid"))
        if not attendees:
            raise SystemExit(
                f"{args.action} 需要通过 --attendees-json、--attendee-names-json、"
                "--attendee-department-id、--attendee-department-name、--attendee-department-path、"
                "--attendee-department-query "
                "或用户解析结果提供参会人信息。"
            )
        body = {"schedule_id": args.schedule_id, "attendees": attendees}
        payload = client.add_attendees(body) if args.action == "add-attendees" else client.del_attendees(body)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "result": payload,
            "resolved_attendees": attendees,
            "resolved_attendee_sources": {
                "names": resolved_name_attendees,
                "department": resolved_department_result,
            },
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "send-reminder":
        touser = args.touser
        if not touser and resolved_user:
            touser = resolved_user["userid"]
        if not touser or not args.content:
            raise SystemExit("send-reminder 需要提供 --content，以及 --touser 或可解析出的用户。")
        payload = client.send_text_message(touser=touser, content=args.content)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "reminder_result": payload,
            "audit_log_path": str(client.audit.path),
        }

    raise SystemExit(f"不支持的操作：{args.action}")


def main() -> int:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args()
    args = apply_request_file(args)
    args = apply_text_file_inputs(args)
    guard_against_garbled_text(args)
    try:
        result = run_action(args)
        write_json(result)
        return 0
    except WeComError as exc:
        write_json(
            {
                "status": "error",
                "message": str(exc),
                "response": exc.response,
            }
        )
        return 1
    except requests.RequestException as exc:
        write_json(
            {
                "status": "error",
                "message": f"网络或 HTTP 请求失败：{exc}",
            }
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
