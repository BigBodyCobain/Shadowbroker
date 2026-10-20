from services.fetchers.acars_summarize import prepare_datalink_display, summarize_datalink_message

# --- Southwest (existing) ---


def test_summarize_track_report():
    text = """++86501,N8997Q,B7378MAX,260620,WN3743,KMSP,KMDW,0496,SMX34-2502-F320
6
N4432.0,W09305.6,201041,15193,-08.3,310,044,CL,00000,0,"""
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "track"
    assert "WN3743" in meta["summary"]
    assert "KMSP→KMDW" in meta["summary"]


def test_summarize_sw_performance_cruise():
    text = """72740,7852,B737-700,260624,WN0120,KABQ,KDEN,1986,SW2501
18.45.14,CR,1575,28981,280.0,.729,-32.3,-06.5,N3601.3,W10655.7,131240
   0.48,FHP,AIR
SIN,-1.42  0.30  0.29"""
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "engine_health"
    assert "WN0120" in meta["summary"]
    assert "cruise" in meta["summary"]


def test_summarize_sw_climb_performance():
    text = """05201,7852,B737-700,260624,WN0120,KABQ,KDEN,1986,SW2501
18.38.08,CL,1149,15631,257.0,.520,000.0,014.5,N3515.4,W10649.4,132800
001.40,001,4100,FLAPS-UP"""
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "climb_perf"
    assert "climb" in meta["summary"]


def test_summarize_trajectory():
    text = """76401
02E24KABQKDEN
N35112W10679318361096P014343008G000022::I0:9W
N35195W10681118371370P006337009G000022::Q0OXW"""
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "trajectory"
    assert "KABQ→KDEN" in meta["summary"]


def test_fragment_hidden():
    text = "0000000,00000000,00000000\n18.38.23,16395,250.2,.510,01.07,01.04,00,00000000"
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "fragment"
    assert meta["hidden"] is True


def test_vdl_binary_hidden():
    text = "014F63N\n)AJQZ)LC0Z0IP-M7O,ZHN3-M,73ZO,UU-ZOS1Z7PPZMSN1ZN"
    meta = summarize_datalink_message(label="37", text=text, source_type="vdl")
    assert meta["hidden"] is True


# --- United / Delta / American ---


def test_united_free_text_position():
    text = "POS N40.123 W074.456 FL350 GS450 1425Z"
    meta = summarize_datalink_message(label="Q0", text=text, source_type="vdl")
    assert meta["kind"] == "position"
    assert "FL350" in meta["summary"]


def test_delta_oooi_out():
    text = "OUT 1425 12JAN KATL"
    meta = summarize_datalink_message(label="00", text=text, source_type="acars")
    assert meta["kind"] == "oooi"
    assert "OUT 1425" in meta["summary"]


def test_american_fi_block():
    text = "FI AA100/AN N100AA/DA KDFW/AA KLAX OUT 1832 OFF 1845"
    meta = summarize_datalink_message(label="44", text=text, source_type="acars")
    assert "AA100" in meta["summary"]
    assert "KDFW→KLAX" in meta["summary"]


def test_united_performance_a320():
    text = """88401,4521,A320-200,260624,UA1234,KORD,KDEN,1200,UA2501
19.10.22,CR,2200,35000,450.0,.820,-45.0,-02.0,N3950.1,W10440.2,125000"""
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "performance"
    assert "UA1234" in meta["summary"]
    assert "KORD→KDEN" in meta["summary"]


# --- International ---


def test_british_airways_engine():
    text = "ENG1 N1 92.5 N2 95.1 EGT 512 FF 2850"
    meta = summarize_datalink_message(label="B1", text=text, source_type="satcom")
    assert meta["kind"] == "engine"


def test_qantas_fi_position():
    text = "FI QF9/AN VH-OQA/DA YSSY/AD EGLL POSN32249E045047,,082806,380,DEBNI"
    meta = summarize_datalink_message(label="H1", text=text, source_type="acars")
    assert meta["kind"] == "position"
    assert "QF9" in meta["summary"]
    assert "YSSY→EGLL" in meta["summary"]


def test_lufthansa_weather():
    text = "WX 250/045 SAT -42 TB MOD EDDF"
    meta = summarize_datalink_message(label="80", text=text, source_type="acars")
    assert meta["kind"] == "weather"
    assert "EDDF" in meta["summary"]


def test_air_france_request():
    text = "REQUEST FL370 DUE TURB"
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "request"
    assert "FL370" in meta["summary"]


# --- Cargo / military ---


def test_fedex_flight():
    text = "++86501,N123FE,B763,260624,FDX1544,KMEM,KORD,0498,SMX34"
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "track"
    assert "FDX1544" in meta["summary"]


def test_military_rch():
    text = "POSN3840.5 W07720.1 FL280 RCH123 KADW KDMA"
    meta = summarize_datalink_message(label="Q0", text=text, source_type="acars")
    assert "RCH123" in meta["summary"]


# --- Ops / misc ---


def test_flight_plan():
    text = "FPN/RI:DA:KJFK:AA:EGLL..MERIT:D:MERIT"
    meta = summarize_datalink_message(label="H1", text=text, source_type="vdl")
    assert meta["kind"] == "flight_plan"
    assert "KJFK→EGLL" in meta["summary"]


def test_departure_report():
    text = "DEP FI DL456/DA KATL/AD KLAX OUT 1205"
    meta = summarize_datalink_message(label="40", text=text, source_type="acars")
    assert meta["kind"] == "dep"
    assert "DL456" in meta["summary"]


def test_pirep():
    text = "#CFB/PIREP MOD TURB FL280 N3845 W09030"
    meta = summarize_datalink_message(label="H1", text=text, source_type="acars")
    assert meta["kind"] == "pirep"


def test_prepare_filters_hidden_and_dedupes():
    messages = [
        {"id": 1, "label": "H1", "text": "POSN35259W106517,KABQ,KDEN", "source_type": "vdl"},
        {"id": 2, "label": "H1", "text": "0000000,00000000,00000000", "source_type": "vdl"},
        {"id": 3, "label": "37", "text": "014F63N\n)AJQZ)LC0Z", "source_type": "vdl"},
        {
            "id": 4,
            "label": "H1",
            "text": "72740,7852,B737-700,260624,WN0120,KABQ,KDEN\n18.45.14,CR,1575,28981",
            "source_type": "vdl",
        },
        {
            "id": 5,
            "label": "H1",
            "text": "72740,7852,B737-700,260624,WN0120,KABQ,KDEN\n18.45.14,CR,1575,28981",
            "source_type": "vdl",
        },
    ]
    display = prepare_datalink_display(messages)
    assert display["hidden_count"] == 3
    assert len(display["messages"]) == 2
