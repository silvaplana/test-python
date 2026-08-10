from hello.main import main


def test_main_prints_expected_output(capsys):
    main()
    captured = capsys.readouterr()
    assert captured.out == "eeerddxsdd\n"
