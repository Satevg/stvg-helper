import json
from unittest.mock import MagicMock, patch

from handler import lambda_handler


def test_lambda_handler_warmup_pings_background_learning():
    with patch("handler.update_heatmap_background") as mock_learning:
        event = {"source": "aws.events"}
        context = MagicMock()

        response = lambda_handler(event, context)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"ok": True}
        assert mock_learning.called


@patch("parking.fetch_cameras_cached")
@patch("parking._fetch_jpeg")
@patch("parking._is_free")
@patch("parking.update_heatmap")
async def test_update_heatmap_background_logic(mock_update, mock_is_free, mock_fetch_jpeg, mock_fetch_cameras):
    from parking import update_heatmap_background

    mock_fetch_cameras.return_value = [
        {
            "title": "Авиационная 8 — Камера 01",
            "name": "cam1",
            "streamer_hostname": "srv",
            "playback_config": {"token": "t"},
        }
    ]
    mock_fetch_jpeg.return_value = b"jpeg_bytes"
    mock_is_free.return_value = (False, [], [])

    # Staleness-weighted selection uses random.choices instead of random.sample
    with patch("random.choices", return_value=[("Авиационная 8", 1)]):
        await update_heatmap_background()

        mock_fetch_cameras.assert_called_once()
        mock_fetch_jpeg.assert_called_once()
        assert mock_is_free.called


@patch("parking.fetch_cameras_cached")
@patch("parking._fetch_jpeg")
@patch("parking._is_free")
async def test_background_selects_4_cameras(mock_is_free, mock_fetch_jpeg, mock_fetch_cameras):
    """Background learning should attempt to scan up to 4 cameras per invocation."""
    from parking import update_heatmap_background

    mock_fetch_cameras.return_value = [
        {
            "title": "Авиационная 8 — Камера 01",
            "name": "cam1",
            "streamer_hostname": "srv",
            "playback_config": {"token": "t"},
        },
        {
            "title": "Авиационная 8 — Камера 02",
            "name": "cam2",
            "streamer_hostname": "srv",
            "playback_config": {"token": "t"},
        },
        {
            "title": "Авиационная 8 — Камера 03",
            "name": "cam3",
            "streamer_hostname": "srv",
            "playback_config": {"token": "t"},
        },
        {
            "title": "Авиационная 8 — Камера 04",
            "name": "cam4",
            "streamer_hostname": "srv",
            "playback_config": {"token": "t"},
        },
    ]
    mock_fetch_jpeg.return_value = b"jpeg_bytes"
    mock_is_free.return_value = (False, [], [])

    # Return 4 unique cameras
    targets = [("Авиационная 8", 1), ("Авиационная 8", 2), ("Авиационная 8", 3), ("Авиационная 8", 4)]
    with patch("random.choices", return_value=targets):
        await update_heatmap_background()

        assert mock_fetch_jpeg.call_count == 4
        assert mock_is_free.call_count == 4


@patch("parking.fetch_cameras_cached")
@patch("parking._fetch_jpeg")
@patch("parking._is_free")
async def test_staleness_weighted_selection(mock_is_free, mock_fetch_jpeg, mock_fetch_cameras):
    """Staleness-weighted selection should call random.choices with weights."""
    from parking import update_heatmap_background

    mock_fetch_cameras.return_value = []
    mock_fetch_jpeg.return_value = b"jpeg_bytes"
    mock_is_free.return_value = (False, [], [])

    with patch("random.choices", return_value=[("Авиационная 8", 1)]) as mock_choices:
        await update_heatmap_background()
        mock_choices.assert_called_once()
        # Verify weights parameter was passed
        _, kwargs = mock_choices.call_args
        assert "weights" in kwargs
        assert "k" in kwargs
        assert kwargs["k"] == 4
