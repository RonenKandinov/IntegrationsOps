from integrationops.cli import main


def test_cli_investigate_inc001(capsys):
    exit_code = main(["investigate", "INC-001"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "INC-001" in captured.out
    assert "below the lender's minimum" in captured.out
    assert "Request amount = 5000" in captured.out
    assert "Lender minimum = 10000" in captured.out
    assert "API response = INVALID_AMOUNT" in captured.out


def test_cli_unknown_incident(capsys):
    exit_code = main(["investigate", "INC-MISSING"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "INC-MISSING" in captured.err


def test_cli_investigate_timeout(capsys):
    exit_code = main(["investigate", "INC-002"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "INC-002" in captured.out
    assert "timed out" in captured.out
    assert "API response = TIMEOUT" in captured.out


def test_cli_investigate_authentication_error(capsys):
    exit_code = main(["investigate", "INC-003"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "INC-003" in captured.out
    assert "not authenticated" in captured.out
    assert "API response = AUTHENTICATION_ERROR" in captured.out
