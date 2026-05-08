import asyncio
import uuid
from sqlalchemy import select
from app.database import AsyncSessionLocal as async_session_factory
from app.models.user import User
from app.models.conversation_session import ConversationSession
from app.api.conversation import send_message, MessageRequest


async def new_session(db, user_id, state, project_id=None):
    s = ConversationSession(
        id=uuid.uuid4(),
        user_id=user_id,
        project_id=project_id,
        current_state=state,
        state_data={},
        messages=[],
        is_active=True,
    )
    db.add(s)
    await db.commit()
    return s


async def case(label, state, content, project_id=None):
    async with async_session_factory() as db:
        u = (await db.execute(select(User).limit(1))).scalar_one()
        s = await new_session(db, u.id, state, project_id)
        try:
            resp = await send_message(
                session_id=s.id,
                req=MessageRequest(content=content),
                current_user=u,
                db=db,
            )
            print(f"[{label}] state={state!r} input={content!r}")
            print(f"  -> role={resp.role} state_after={resp.state}")
            print(f"  msg: {resp.content[:160]}")
        except Exception as e:
            print(f"[{label}] EXC: {e!r}")
        print()


async def case_button_start_search(label, state):
    """模拟点击检索按钮 → 调 start_round 端点。"""
    from fastapi import HTTPException
    from app.api.search import start_round
    from app.models.project import Project
    async with async_session_factory() as db:
        u = (await db.execute(select(User).limit(1))).scalar_one()
        proj = (await db.execute(select(Project).where(Project.user_id == u.id).limit(1))).scalar_one_or_none()
        if proj is None:
            print(f"[{label}] SKIP: 无项目"); print(); return
        # 准备一个该 state 的 session 挂到该 project 下
        s = ConversationSession(
            id=uuid.uuid4(), user_id=u.id, project_id=proj.id,
            current_state=state, state_data={"collaboration": {"archived": False}} if "collab" in state else {},
            messages=[], is_active=True,
        )
        db.add(s); await db.commit()
        try:
            r = await start_round(project_id=proj.id, current_user=u, db=db)
            print(f"[{label}] session.state={state!r} -> 放行 round_id={r.id}")
        except HTTPException as e:
            print(f"[{label}] session.state={state!r} -> 拦截 {e.status_code} {e.detail[:120]}")
        print()


async def case_button_enter_collab(label, state):
    """模拟点击"协作研究"按钮 → 调 suggest_scope 端点。"""
    from fastapi import HTTPException
    from app.api.collaboration import suggest_scope
    from app.models.project import Project
    async with async_session_factory() as db:
        u = (await db.execute(select(User).limit(1))).scalar_one()
        # 需要关联项目否则 400 前置拒绝
        proj = (await db.execute(select(Project).where(Project.user_id == u.id).limit(1))).scalar_one_or_none()
        if proj is None:
            print(f"[{label}] SKIP: 当前用户没有项目，无法模拟按钮路径")
            print(); return
        s = ConversationSession(
            id=uuid.uuid4(), user_id=u.id, project_id=proj.id,
            current_state=state, state_data={}, messages=[], is_active=True,
        )
        db.add(s); await db.commit()
        try:
            r = await suggest_scope(session_id=s.id, current_user=u, db=db)
            print(f"[{label}] state={state!r} -> 放行 state_after={r.get('state')}")
        except HTTPException as e:
            print(f"[{label}] state={state!r} -> 拦截 {e.status_code} {e.detail[:120]}")
        print()


async def main():
    print("=== 自然语言路径（send_message dispatcher）===\n")
    await case("A. 协作active禁检索", "collaboration_active", "开始新一轮检索")
    await case("B. 协作selecting闲聊被挡", "collaboration_selecting", "你好")
    await case("C. 协作selecting输「取消」退出", "collaboration_selecting", "取消")
    await case("D. intent_confirmation补充", "intent_confirmation", "我想研究锂电池")
    await case("E. 非idle兜底(search_mode_selection)", "search_mode_selection", "随便说句话")
    await case("F. 非idle兜底(keyword_confirmation)", "keyword_confirmation", "换个话题")

    print("=== 检索按钮路径（start_round）— 只测拦截，放行路径会触发真实 Celery 检索 ===\n")
    await case_button_start_search("N. 协作active下点新检索", "collaboration_active")

    print("=== 按钮路径（suggest_scope API）===\n")
    await case_button_enter_collab("G. idle 允许进协作", "idle")
    await case_button_enter_collab("H. 检索中禁入协作(intent_confirmation)", "intent_confirmation")
    await case_button_enter_collab("I. 检索中禁入协作(keyword_confirmation)", "keyword_confirmation")
    await case_button_enter_collab("J. 检索中禁入协作(search_mode_selection)", "search_mode_selection")
    await case_button_enter_collab("K. 协作active中不重复进", "collaboration_active")
    await case_button_enter_collab("L. collaboration_selecting 允许重选", "collaboration_selecting")


asyncio.run(main())
