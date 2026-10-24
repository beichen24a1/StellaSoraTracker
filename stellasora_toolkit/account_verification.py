"""Combine the in-game player UID with the generic Lua UID field.

The player table / ``UID:`` label is what the game shows and what the upload
service expects. Some clients also expose an unrelated ``nUid``-style field
(e.g. an internal account/installation id). That field must not override the
in-game UID; it is only used as a fallback when the player table is unavailable.
"""
from .account_uid import UidSearch, find_account_uid
from .uid import read_game_uid_from_process, AmbiguousUidError
from .account_guard import AccountSafetyError


def verified_uid_search(process, discovery, field_hint='') -> UidSearch:
    try:
        player_uid = read_game_uid_from_process(process)
    except AmbiguousUidError as error:
        raise AccountSafetyError(str(error)) from error
    except LookupError:
        player_uid = ''
    if player_uid:
        # 游戏内玩家表/UID 标签优先; 不返回字段名, 避免把通用 Lua 字段名
        # (可能对应 nUid 这类内部 ID)当成下次的快速通道。
        return UidSearch(uid=player_uid, field_name='')

    learned = find_account_uid(discovery, field_hint=field_hint)
    if learned.ambiguous or learned.budget_exceeded:
        raise AccountSafetyError('UID 候选不唯一或扫描超时，已停止保存，请稍后重试')
    if not learned.uid:
        raise AccountSafetyError(
            '未找到唯一的游戏 UID，已停止保存，不会沿用手填或旧账号 UID；'
            '请先进入游戏主界面或个人资料页，再点读取重试')
    return learned
