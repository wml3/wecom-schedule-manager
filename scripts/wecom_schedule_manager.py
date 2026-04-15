#!/usr/bin/env python
"""
企业微信日程管理命令行工具。

本脚本不会内置真实租户参数。请通过命令行参数、环境变量或 UTF-8 请求
文件提供运行时所需配置，具体说明见 references/configuration.md。
"""

from __future__ import annotations

import argparse
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

    def resolve_user(
        self,
        *,
        user_id: Optional[str],
        mobile: Optional[str],
        email: Optional[str],
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
        raise SystemExit("请至少提供一种用户标识：--user-id、--mobile 或 --email，以便完成可审计的用户解析。")

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


def parse_attendees(attendees_json: Optional[str], default_userid: Optional[str]) -> List[Dict[str, str]]:
    attendees = parse_json(attendees_json, [])
    if attendees:
        return attendees
    if default_userid:
        return [{"userid": default_userid}]
    return []


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


def apply_request_file(args: argparse.Namespace) -> argparse.Namespace:
    payload = None
    if args.request_file:
        payload = json.loads(Path(args.request_file).read_text(encoding="utf-8-sig"))
    elif args.request_stdin:
        payload = json.loads(read_stdin_json_text())
    if payload is None:
        return args
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
            "create-schedule",
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
    parser.add_argument("--public-range-json", help="public_range 对应的 JSON 对象。")
    parser.add_argument("--shares-file", help="共享对象对应的 UTF-8 JSON 文件。")
    parser.add_argument("--attendees-file", help="参会人对应的 UTF-8 JSON 文件。")
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


def resolve_primary_user(client: WeComClient, args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if args.user_id or args.mobile or args.email:
        return client.resolve_user(user_id=args.user_id, mobile=args.mobile, email=args.email)
    return None


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
        raise SystemExit("--auto-create-calendar 需要先通过 --user-id、--mobile 或 --email 解析出有效用户。")
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


def merged_update_schedule(
    current: Dict[str, Any],
    args: argparse.Namespace,
    resolved_user: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if args.skip_attendees:
        attendees = normalize_attendees(current.get("attendees"))
    elif args.attendees_json:
        attendees = normalize_attendees(parse_attendees(args.attendees_json, None) or current.get("attendees"))
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


def run_action(args: argparse.Namespace) -> Dict[str, Any]:
    client = build_client(args)
    resolved_user = resolve_primary_user(client, args)
    auto_calendar = maybe_auto_create_calendar(client, args, resolved_user)
    effective_cal_id = env_or_value(args.cal_id, "WECOM_CAL_ID", required=False) or (
        auto_calendar or {}
    ).get("cal_id")

    if args.action == "resolve-user":
        if not resolved_user:
            raise SystemExit("resolve-user 需要提供 --user-id、--mobile 或 --email。")
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "resolved_user": resolved_user,
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "create-calendar":
        if auto_calendar:
            calendar = auto_calendar
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
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "calendar": calendar,
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

    if args.action == "create-schedule":
        user_id = (resolved_user or {}).get("userid")
        if not args.start or not args.end:
            raise SystemExit("create-schedule 需要提供 --start 和 --end。")
        schedule = {
            "start_time": parse_time(args.start),
            "end_time": parse_time(args.end),
            "attendees": parse_attendees(args.attendees_json, user_id),
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
            "created_schedule": payload,
            "effective_cal_id": schedule["cal_id"],
            "audit_log_path": str(client.audit.path),
        }

    if args.action == "update-schedule":
        if not args.schedule_id:
            raise SystemExit("update-schedule 需要提供 --schedule-id。")
        current_payload = client.get_schedule([args.schedule_id])
        schedule_list = current_payload.get("schedule_list") or []
        if not schedule_list:
            raise SystemExit(f"未找到日程：{args.schedule_id}")
        body = merged_update_schedule(schedule_list[0], args, resolved_user)
        payload = client.update_schedule(body)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "updated_schedule": payload,
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
        attendees = parse_attendees(args.attendees_json, (resolved_user or {}).get("userid"))
        if not attendees:
            raise SystemExit(f"{args.action} 需要通过 --attendees-json 或用户解析结果提供参会人信息。")
        body = {"schedule_id": args.schedule_id, "attendees": attendees}
        payload = client.add_attendees(body) if args.action == "add-attendees" else client.del_attendees(body)
        return {
            "request_id": client.audit.request_id,
            "channel": "wecom",
            "result": payload,
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
