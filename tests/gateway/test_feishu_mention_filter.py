from types import SimpleNamespace

from marneo.gateway.adapters.feishu import FeishuChannelAdapter


def mention(*, open_id="", user_id="", name="", key=""):
    return SimpleNamespace(
        id=SimpleNamespace(open_id=open_id, user_id=user_id),
        name=name,
        key=key,
    )


def sender(*, sender_type="bot", open_id="", user_id=""):
    return SimpleNamespace(
        sender_type=sender_type,
        sender_id=SimpleNamespace(open_id=open_id, user_id=user_id),
    )


def adapter_with_identity(*, open_id="", user_id="", name=""):
    adapter = FeishuChannelAdapter(manager=None, employee_name="laoqi")
    adapter._bot_open_id = open_id
    adapter._bot_user_id = user_id
    adapter._bot_name = name
    return adapter


def test_message_mentions_this_bot_by_open_id():
    adapter = adapter_with_identity(open_id="ou_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(open_id="ou_bot", name="Someone Else Label")
    ]) is True


def test_message_does_not_mention_this_bot_when_open_id_differs_even_if_name_matches():
    adapter = adapter_with_identity(open_id="ou_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(open_id="ou_other", name="Bot")
    ]) is False


def test_message_mentions_this_bot_by_user_id_when_open_id_missing():
    adapter = adapter_with_identity(user_id="u_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(user_id="u_bot", name="Wrong Label")
    ]) is True


def test_message_does_not_mention_this_bot_when_user_id_differs_even_if_name_matches():
    adapter = adapter_with_identity(user_id="u_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(user_id="u_other", name="Bot")
    ]) is False


def test_message_mentions_this_bot_by_name_only_when_ids_unavailable():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot", name="Bot")

    assert adapter._message_mentions_this_bot([
        mention(name="Bot")
    ]) is True


def test_any_mention_does_not_match_when_bot_identity_missing():
    adapter = adapter_with_identity()

    assert adapter._message_mentions_this_bot([
        mention(open_id="ou_someone", user_id="u_someone", name="Someone")
    ]) is False


def test_self_sent_bot_message_drops_by_open_id():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._is_self_sent_bot_message(
        sender(sender_type="bot", open_id="ou_bot", user_id="u_other")
    ) is True


def test_self_sent_bot_message_drops_by_user_id_when_open_id_missing():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._is_self_sent_bot_message(
        sender(sender_type="bot", user_id="u_bot")
    ) is True


def test_self_sent_filter_allows_other_bots():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._is_self_sent_bot_message(
        sender(sender_type="bot", open_id="ou_other", user_id="u_other")
    ) is False


def test_self_sent_filter_ignores_human_sender_even_if_id_matches():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._is_self_sent_bot_message(
        sender(sender_type="user", open_id="ou_bot", user_id="u_bot")
    ) is False


def test_group_policy_disabled_rejects_group_message():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "disabled"

    assert adapter._should_accept_group_message(
        raw_content="@_user_1 hello",
        mentions=[mention(open_id="ou_bot")],
    ) is False


def test_group_policy_open_accepts_without_mention():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "open"

    assert adapter._should_accept_group_message(raw_content="hello", mentions=[]) is True


def test_group_policy_at_only_accepts_explicit_bot_mention():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "at_only"

    assert adapter._should_accept_group_message(
        raw_content="@_user_1 hello",
        mentions=[mention(open_id="ou_bot")],
    ) is True


def test_group_policy_at_only_rejects_any_other_mention():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "at_only"

    assert adapter._should_accept_group_message(
        raw_content="@_user_1 hello",
        mentions=[mention(open_id="ou_other")],
    ) is False


def test_group_policy_at_only_does_not_accept_at_all_by_default():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "at_only"

    assert adapter._should_accept_group_message(raw_content="@_all hello", mentions=[]) is False


def test_group_policy_all_only_accepts_at_all():
    adapter = adapter_with_identity(open_id="ou_bot")
    adapter._group_policy = "all_only"

    assert adapter._should_accept_group_message(raw_content="@_all hello", mentions=[]) is True


def test_collect_non_self_mentions_excludes_this_bot_by_open_id_and_user_id():
    adapter = adapter_with_identity(open_id="ou_bot", user_id="u_bot")

    assert adapter._collect_non_self_mentions([
        mention(open_id="ou_bot", user_id="u_x", name="BotByOpen"),
        mention(open_id="ou_x", user_id="u_bot", name="BotByUser"),
        mention(open_id="ou_other", user_id="u_other", name="Other"),
    ]) == [{"name": "Other", "open_id": "ou_other", "user_id": "u_other"}]


def test_strip_feishu_mentions_removes_named_placeholders_and_at_all():
    assert FeishuChannelAdapter._strip_feishu_mentions(
        "@Bot @_user_1 @_all hello",
        [mention(name="Bot")],
    ) == "hello"
