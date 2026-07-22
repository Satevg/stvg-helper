from unittest.mock import MagicMock, patch

import pytest

from xvideo.service import extract_tweet_id, get_video_url


class TestExtractTweetId:
    @pytest.mark.parametrize(
        "url",
        [
            "https://x.com/user/status/1234567890",
            "https://twitter.com/user/status/1234567890",
            "https://mobile.twitter.com/user/status/1234567890",
            "https://www.x.com/user/status/1234567890",
            "https://vxtwitter.com/user/status/1234567890",
            "https://fxtwitter.com/user/status/1234567890",
            "check this out https://x.com/user/status/1234567890?s=20 cool",
        ],
    )
    def test_valid_links(self, url):
        assert extract_tweet_id(url) == "1234567890"

    @pytest.mark.parametrize(
        "text",
        [
            "https://x.com/user",
            "https://youtube.com/watch?v=1234567890",
            "just some text",
            "https://x.com/user/status/",
        ],
    )
    def test_non_matching(self, text):
        assert extract_tweet_id(text) is None


def _resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class TestGetVideoUrl:
    def test_fxtwitter_picks_mp4(self):
        payload = {
            "tweet": {
                "media": {
                    "videos": [
                        {"url": "https://cdn/low.mp4", "format": "video/mp4"},
                    ]
                }
            }
        }
        with patch("xvideo.service.requests.get", return_value=_resp(payload)) as mock_get:
            assert get_video_url("1") == "https://cdn/low.mp4"
            mock_get.assert_called_once()

    def test_no_video_returns_none(self):
        payload = {"tweet": {"media": {"videos": []}}}
        with patch("xvideo.service.requests.get", return_value=_resp(payload)):
            # Both fx and vx return empty; result is None.
            assert get_video_url("1") is None

    def test_falls_back_to_vxtwitter(self):
        fx_payload = {"tweet": {"media": {"videos": []}}}
        vx_payload = {"mediaURLs": ["https://cdn/video.mp4"]}

        def side_effect(url, *args, **kwargs):
            return _resp(vx_payload if "vxtwitter" in url else fx_payload)

        with patch("xvideo.service.requests.get", side_effect=side_effect):
            assert get_video_url("1") == "https://cdn/video.mp4"

    def test_fx_exception_falls_back(self):
        vx_payload = {"mediaURLs": ["https://cdn/video.mp4"]}

        def side_effect(url, *args, **kwargs):
            if "fxtwitter" in url:
                raise RuntimeError("boom")
            return _resp(vx_payload)

        with patch("xvideo.service.requests.get", side_effect=side_effect):
            assert get_video_url("1") == "https://cdn/video.mp4"
