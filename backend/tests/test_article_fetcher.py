from app.services.article_fetcher import (
    extract_cgi_data_content_html,
    extract_original_article_url,
    is_weread_content_url,
)


def test_extract_cgi_data_content_html_from_jsdecode() -> None:
    html = """<script>window.cgiDataNew = {
        content_noencode: JsDecode('<section><p>原有格式</p></section>')
    };</script>"""

    assert extract_cgi_data_content_html(html) == "<section><p>原有格式</p></section>"


def test_extract_cgi_data_content_html_from_single_quoted_string() -> None:
    html = r"""<script>window.cgiDataNew = {
        content_noencode: '<section><p>直接字符串，含\'引号\'</p></section>'
    };</script>"""

    assert extract_cgi_data_content_html(html) == "<section><p>直接字符串，含'引号'</p></section>"


def test_extract_cgi_data_content_html_from_double_quoted_string() -> None:
    html = r'''<script>window.cgiDataNew = {
        content_noencode: "<section><p>double \"quoted\"</p></section>"
    };</script>'''

    assert extract_cgi_data_content_html(html) == '<section><p>double "quoted"</p></section>'


def test_extract_original_article_url_from_meta() -> None:
    html = (
        '<meta property="og:url" '
        'content="https://mp.weixin.qq.com/s?__biz=abc&amp;mid=123&amp;idx=1">'
    )

    assert extract_original_article_url(html) == (
        "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1"
    )


def test_extract_original_article_url_from_msg_link() -> None:
    html = (
        "var msg_link = "
        "'https://mp.weixin.qq.com/s?__biz=abc\\x26mid=123\\x26idx=1';"
    )

    assert extract_original_article_url(html) == (
        "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1"
    )


def test_extract_original_article_url_rejects_weread_content_endpoint() -> None:
    html = (
        '<meta property="og:url" '
        'content="https://weread.qq.com/web/mp/content?reviewId=review">'
    )

    assert extract_original_article_url(html) is None
    assert is_weread_content_url(
        "https://weread.qq.com/web/mp/content?reviewId=review"
    )
    assert not is_weread_content_url("https://mp.weixin.qq.com/s?__biz=abc")
