"""Reviewed prose corrections for published endings and existing saved results.

Exact context replacements preserve the published package identity and all rules.
Do not deduplicate arbitrary sentences: repeated dialogue may be intentional.
"""

ENDING_PROSE_CORRECTIONS = (
    (
        "你把进度押在了最快的那条路上。快的路也记账",
        "快的路也记账",
    ),
    (
        "你说我知道。他不说话了。他到最后也没弄明白",
        "你说我知道。他到最后也没弄明白",
    ),
    (
        "至少数字上是。你也把它变成了另一个样子。赵建国那句",
        "至少数字上是。赵建国那句",
    ),
    (
        "你到现在还记得。你走过一整条街，一个招呼都没有。村委会门口",
        "你到现在还记得。村委会门口",
    ),
    (
        "村委会门口的老人一见你就站起来往屋里走。没有人骂你，也没有人拦你，所有人往旁边让，让得客客气气，让得干干净净。这份干净比骂声还重",
        "村委会门口的老人一见你就站起来往屋里走。这种疏远比骂声还重",
    ),
    (
        "你交的每一份材料都是实的。真话说出去了，污染处置却仍未落实。这是一种",
        "你交的每一份材料都是实的。这是一种",
    ),
)


def revise_ending_prose(text: str) -> str:
    for original, revised in ENDING_PROSE_CORRECTIONS:
        text = text.replace(original, revised)
    return text
