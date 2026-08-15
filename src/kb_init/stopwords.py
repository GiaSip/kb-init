"""内置功能词表。

**这张表按定义覆盖不了没收录的语言**——单一语言独占一个簇时，该语言的功能词
会被判为区分性关键词。这是已知失效模式（2B spec §4.4），产品层的兜底是「关键词
永远与证据标题同时呈现 + 人肉 gate 可取消勾选 + L3 可重命名」，不是把这张表
无限加长。加语言之前先问：这门语言的簇真的出现过吗？
"""
from __future__ import annotations

STOPLIST_VERSION = "bundled-v1"

_EN = """a about above after again against all also am an and any are as at be
because been before being below between both but by can cannot could did do does
doing down during each few for from further had has have having he her here hers
him his how i if in into is it its just like me more most my no nor not now of
off on once only or other our out over own same she should so some such than that
the their them then there these they this those through to too under until up
very was we were what when where which while who whom why will with would you
your world things thing get got make made take taken
people time said long way much many new good day year back still even well first
last know knew think see seen going really something someone anything everything
one two three next another every always never often sometimes maybe want need
look looked come came go goes went give given put use used"""

_IT = """a ad agli ai al alla alle allo anche c che chi ci co coi col come con
contro cui da dagli dai dal dalla dalle dallo degli dei del della delle dello di
dov dove e ed essere fa fare gli ha hai hanno ho i il in io la le lo loro ma me
mi ne negli nei nel nella nelle nello no noi non o per perche piu quale quando
quel quella quelle quello questa queste questi questo sara se sei si sia siamo
sono su sugli sui sul sulla sulle suo sua tra tu tuo un una uno vi voi
bene piu più tempo andare cosa molto dopo ancora sempre poi gia già oggi ogni
tutto tutti tutta tutte fatto detto stato stata cosi così solo prima adesso
niente nulla qualcosa qualche altro altra altri altre grande piccolo"""

FUNCTION_WORDS = frozenset(_EN.split()) | frozenset(_IT.split())

# 中文没有词边界，n-gram 会切出「是周」「们这」这类非词。这些黏着字单独出现
# 在 n-gram 里通常意味着切错了，而不是命中了一个词。
CJK_GLUE = frozenset(
    "的了是在我们这那和就有也都要会对上下不与及其之为以于把被让给从向"
    "很还再又才只使得所因但如果虽然"
)
