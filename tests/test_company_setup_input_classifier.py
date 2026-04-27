"""企业设立输入分类规则。"""

from govflow.company_setup.input_classifier import (
    looks_like_meta_or_clarify,
    looks_like_topic_deferral,
    review_poll_should_advance,
)


def test_meta_question() -> None:
    assert looks_like_meta_or_clarify("这是什么意思？")
    assert looks_like_meta_or_clarify("不懂怎么填")
    assert not looks_like_meta_or_clarify("南宁市青秀区民族大道1号")


def test_topic_deferral() -> None:
    assert looks_like_topic_deferral("换个话题先")
    assert not looks_like_topic_deferral("张三50%")


def test_review_advance_keywords() -> None:
    assert review_poll_should_advance("继续")
    assert review_poll_should_advance("帮我查一下进度")
    assert not review_poll_should_advance("什么意思")
    assert not review_poll_should_advance("")
