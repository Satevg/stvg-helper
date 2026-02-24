import json
from unittest.mock import MagicMock, patch

from handler import lambda_handler


def test_lambda_handler_warmup_pings_background_learning():
    # Mock update_heatmap_background to verify it's called
    # We use a regular MagicMock because run_until_complete is called inside
    with patch("handler.update_heatmap_background") as mock_learning:
        event = {"source": "aws.events"}
        context = MagicMock()
        
        response = lambda_handler(event, context)
        
        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"ok": True}
        assert mock_learning.called


@patch("parking.fetch_cameras")
@patch("parking._fetch_jpeg")
@patch("parking._is_free")
@patch("parking.update_heatmap")
async def test_update_heatmap_background_logic(mock_update, mock_is_free, mock_fetch_jpeg, mock_fetch_cameras):
    from parking import update_heatmap_background
    
    # Mock cameras list
    mock_fetch_cameras.return_value = [{"title": "Авиационная 8 — Камера 01", "name": "cam1", "streamer_hostname": "srv", "playback_config": {"token": "t"}}]
    mock_fetch_jpeg.return_value = b"jpeg_bytes"
    mock_is_free.return_value = (False, [], [])
    
    # We want to make sure it doesn't crash and processes at least one camera if lucky with random
    with patch("random.sample", return_value=[("Авиационная 8", 1)]):
        await update_heatmap_background()
        
        mock_fetch_cameras.assert_called_once()
        mock_fetch_jpeg.assert_called_once()
        assert mock_is_free.called
