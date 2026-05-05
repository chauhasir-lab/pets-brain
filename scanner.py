def send_test_alert():
    send_alert(
        symbol="TEST",
        action="BUY",
        entry=100,
        sl=95,
        target=110,
        confidence=85,
        reason="System test"
    )
