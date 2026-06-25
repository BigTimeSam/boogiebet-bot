"""Fake telegram objects for driving handlers in tests.

telegram is stubbed in conftest, so handlers receive these lightweight stand-ins
instead of real Update / Context / Bot / CallbackQuery objects. They record what
the handler tried to send so tests can assert on it.
"""
from types import SimpleNamespace


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.deleted = []
        self._mid = 1000

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self._mid += 1
        self.sent.append({"chat_id": chat_id, "text": text})
        return SimpleNamespace(message_id=self._mid)

    async def edit_message_text(self, text, chat_id=None, message_id=None, reply_markup=None, **kw):
        self.edited.append({"chat_id": chat_id, "message_id": message_id, "text": text})

    async def delete_message(self, chat_id, message_id, **kw):
        self.deleted.append({"chat_id": chat_id, "message_id": message_id})


class FakeMessage:
    def __init__(self, text=None, chat_id=1, message_id=1):
        self.text = text
        self.chat_id = chat_id
        self.message_id = message_id
        self.replies = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.replies.append(text)
        return SimpleNamespace(message_id=999)


class FakeContext:
    def __init__(self, bot=None, user_data=None, args=None):
        self.bot = bot or FakeBot()
        self.user_data = {} if user_data is None else user_data
        self.args = args or []


class FakeQuery:
    """A callback_query: records .answer() calls and exposes .message / .data."""

    def __init__(self, data, user_id=1, chat_id=1, message_id=1, bot=None):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage(chat_id=chat_id, message_id=message_id)
        self.answers = []
        self._bot = bot or FakeBot()

    async def answer(self, text=None, show_alert=False, **kw):
        self.answers.append({"text": text, "show_alert": show_alert})

    def get_bot(self):
        return self._bot


def make_update(text, user_id=1, chat_id=1, username="alice"):
    """A message update (free-text / command)."""
    return SimpleNamespace(
        message=FakeMessage(text=text, chat_id=chat_id, message_id=1),
        effective_user=SimpleNamespace(id=user_id, username=username, first_name=username),
        effective_chat=SimpleNamespace(id=chat_id),
        get_bot=lambda: FakeBot(),
    )


def make_callback_update(query):
    """An update carrying a callback_query."""
    return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=query.from_user.id))
