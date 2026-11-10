from lyrics_pro.diagnostics import setup, event, logger


def test_cli_log_rotation_and_message_bounds(tmp_path):
    old_handlers = logger.handlers[:]
    try:
        setup(directory=tmp_path)
        handler = logger.handlers[0]
        handler.maxBytes = 1024
        handler.backupCount = 2
        for number in range(20):
            event("test", number=number, error="x" * 10000)
        handler.flush()
        files = list(tmp_path.glob("cli.log*"))
        assert len(files) == 3
        assert all(path.stat().st_size <= 1024 for path in files)
        assert '"number": "19"' in (tmp_path / "cli.log").read_text()
        assert "x" * 513 not in (tmp_path / "cli.log").read_text()
    finally:
        for handler in logger.handlers: handler.close()
        logger.handlers = old_handlers
