from app.services.article_fetcher import extract_cgi_data_content_html


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
