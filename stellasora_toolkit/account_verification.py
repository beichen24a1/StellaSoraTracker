"""Combine learned Lua fields and upstream UID/player-table checks without guessing."""
from .account_uid import UidSearch, find_account_uid
from .uid import read_game_uid_from_process, AmbiguousUidError
from .account_guard import AccountSafetyError


def verified_uid_search(process, discovery, field_hint='') -> UidSearch:
    learned = find_account_uid(discovery, field_hint=field_hint)
    if learned.ambiguous or learned.budget_exceeded:
        raise AccountSafetyError('UID 候选不唯一或扫描超时，已停止保存，请重启游戏后重试')
    try:
        player_uid = read_game_uid_from_process(process)
    except AmbiguousUidError as error:
        raise AccountSafetyError(str(error)) from error
    except LookupError:
        player_uid = ''
    candidates = {value for value in (learned.uid, player_uid) if value}
    if len(candidates) != 1:
        raise AccountSafetyError('未找到唯一的游戏 UID，已停止保存，不会沿用手填或旧账号 UID')
    uid = candidates.pop()
    return UidSearch(uid=uid, field_name=learned.field_name if learned.uid else '_nPlayerId / UID:')
