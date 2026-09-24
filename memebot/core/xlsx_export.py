"""Builds a formatted, color-coded .xlsx workbook from trade log rows.

Shared by scripts/format_trade_log.py (run manually) and the Telegram
/export command (bot.py) so both produce identical output from one
implementation.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
BODY_FONT = Font(name="Arial")
WIN_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
LOSS_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

COLUMNS = [
    ("closed_at", "Closed At", 19, None),
    ("opened_at", "Opened At", 19, None),
    ("mode", "Mode", 8, None),
    ("symbol", "Symbol", 12, None),
    ("token_address", "Token Address", 24, None),
    ("entry_price", "Entry Price ($)", 16, "0.00000000"),
    ("close_price", "Close Price ($)", 16, "0.00000000"),
    ("size_sol", "Size (SOL)", 12, "0.00000"),
    ("pnl_sol", "PnL (SOL)", 12, "+0.00000;-0.00000"),
    ("pnl_pct", "PnL (%)", 10, "+0.0%;-0.0%"),
    ("close_reason", "Close Reason", 14, None),
]


def build_workbook(rows: list[dict]) -> Workbook:
    wb = Workbook()
    trades_ws = wb.active
    trades_ws.title = "Trades"

    for col_idx, (_key, label, width, _fmt) in enumerate(COLUMNS, start=1):
        cell = trades_ws.cell(row=1, column=col_idx, value=label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        trades_ws.column_dimensions[get_column_letter(col_idx)].width = width

    numeric_keys = {"entry_price", "close_price", "size_sol", "pnl_sol", "pnl_pct"}
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, (key, _label, _width, fmt) in enumerate(COLUMNS, start=1):
            raw = row.get(key, "")
            value = raw
            if key in numeric_keys and raw not in ("", None):
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
            cell = trades_ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = BODY_FONT
            if fmt and isinstance(value, float):
                cell.number_format = fmt

    trades_ws.freeze_panes = "A2"

    last_row = max(len(rows) + 1, 2)
    pnl_col_letter = get_column_letter(next(i for i, c in enumerate(COLUMNS, 1) if c[0] == "pnl_sol"))
    pct_col_letter = get_column_letter(next(i for i, c in enumerate(COLUMNS, 1) if c[0] == "pnl_pct"))
    for col_letter in (pnl_col_letter, pct_col_letter):
        rng = f"{col_letter}2:{col_letter}{last_row}"
        trades_ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"], fill=WIN_FILL))
        trades_ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"], fill=LOSS_FILL))

    # --- Summary sheet: real formulas referencing Trades, never hardcoded ---
    summary_ws = wb.create_sheet("Summary")
    summary_ws.column_dimensions["A"].width = 22
    summary_ws.column_dimensions["B"].width = 16

    header_a = summary_ws.cell(row=1, column=1, value="Metric")
    header_b = summary_ws.cell(row=1, column=2, value="Value")
    for cell in (header_a, header_b):
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    metrics = [
        ("Total Trades", f"=COUNT(Trades!{pnl_col_letter}2:{pnl_col_letter}{last_row})", None),
        ("Wins", f'=COUNTIF(Trades!{pnl_col_letter}2:{pnl_col_letter}{last_row},">0")', None),
        ("Losses", f'=COUNTIF(Trades!{pnl_col_letter}2:{pnl_col_letter}{last_row},"<=0")', None),
        ("Win Rate", "=IF(B2=0,\"n/a\",B3/B2)", "0.0%"),
        ("Total PnL (SOL)", f"=SUM(Trades!{pnl_col_letter}2:{pnl_col_letter}{last_row})", "+0.00000;-0.00000"),
        ("Best Trade (SOL)", f'=IF(B2=0,"n/a",MAX(Trades!{pnl_col_letter}2:{pnl_col_letter}{last_row}))', "+0.00000;-0.00000"),
        ("Worst Trade (SOL)", f'=IF(B2=0,"n/a",MIN(Trades!{pnl_col_letter}2:{pnl_col_letter}{last_row}))', "+0.00000;-0.00000"),
    ]
    for row_idx, (label, formula, fmt) in enumerate(metrics, start=2):
        summary_ws.cell(row=row_idx, column=1, value=label).font = BODY_FONT
        value_cell = summary_ws.cell(row=row_idx, column=2, value=formula)
        value_cell.font = BODY_FONT
        if fmt:
            value_cell.number_format = fmt

    if not rows:
        note = summary_ws.cell(
            row=len(metrics) + 3,
            column=1,
            value="No closed trades yet — this fills in automatically once the bot closes its first position.",
        )
        note.font = Font(name="Arial", italic=True, color="6B7280")

    return wb


BACKTEST_COLUMNS = [
    "Symbol",
    "Entry Time",
    "Entry Price ($)",
    "Exit Time",
    "Exit Price ($)",
    "Stop Loss ($)",
    "Take Profit ($)",
    "Size (SOL)",
    "PnL (SOL)",
    "PnL (%)",
    "R-Multiple",
    "Exit Reason",
]


def build_backtest_workbook(results: list) -> Workbook:
    """results: list[memebot.backtest.engine.BacktestResult], one per symbol tested."""
    wb = Workbook()
    trades_ws = wb.active
    trades_ws.title = "Trades"

    for col_idx, label in enumerate(BACKTEST_COLUMNS, start=1):
        cell = trades_ws.cell(row=1, column=col_idx, value=label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        trades_ws.column_dimensions[get_column_letter(col_idx)].width = 16
    trades_ws.column_dimensions["A"].width = 12
    trades_ws.column_dimensions["L"].width = 14

    row_idx = 2
    for result in results:
        for t in result.trades:
            values = [
                t.symbol,
                t.entry_time.strftime("%Y-%m-%d %H:%M"),
                t.entry_price,
                t.exit_time.strftime("%Y-%m-%d %H:%M"),
                t.exit_price,
                t.stop_loss,
                t.take_profit,
                t.size_sol,
                t.pnl_sol,
                t.pnl_pct,
                t.r_multiple,
                t.exit_reason,
            ]
            formats = [None, None, "0.00000000", None, "0.00000000", "0.00000000", "0.00000000",
                       "0.00000", "+0.00000;-0.00000", "+0.0%;-0.0%", "+0.00;-0.00", None]
            for col_idx, (value, fmt) in enumerate(zip(values, formats), start=1):
                cell = trades_ws.cell(row=row_idx, column=col_idx, value=value)
                cell.font = BODY_FONT
                if fmt:
                    cell.number_format = fmt
            row_idx += 1

    last_row = max(row_idx - 1, 2)
    trades_ws.freeze_panes = "A2"
    for col_letter in ("I", "K"):  # PnL (SOL), R-Multiple
        rng = f"{col_letter}2:{col_letter}{last_row}"
        trades_ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"], fill=WIN_FILL))
        trades_ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"], fill=LOSS_FILL))

    # --- Summary sheet: one row per symbol, plus a combined total row.
    # Total Trades/Wins/Losses/Total PnL/Avg R are real formulas over the
    # Trades sheet. Total Return % and Max Drawdown % are NOT — they depend
    # on the sequential, compounding order trades closed in, which isn't
    # expressible as a simple range aggregate — so those two are written as
    # the Python backtest's own computed values (noted below, not hidden).
    summary_ws = wb.create_sheet("Summary")
    headers = ["Symbol", "Total Trades", "Wins", "Losses", "Win Rate", "Total PnL (SOL)", "Avg R-Multiple",
               "Total Return % *", "Max Drawdown % *"]
    for col_idx, label in enumerate(headers, start=1):
        cell = summary_ws.cell(row=1, column=col_idx, value=label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        summary_ws.column_dimensions[get_column_letter(col_idx)].width = 16

    for i, result in enumerate(results, start=2):
        s = result.summary
        symbol_cell = summary_ws.cell(row=i, column=1, value=result.symbol)
        symbol_cell.font = BODY_FONT

        formulas = [
            f'=COUNTIF(Trades!$A$2:$A${last_row},A{i})',
            f'=COUNTIFS(Trades!$A$2:$A${last_row},A{i},Trades!$I$2:$I${last_row},">0")',
            f'=COUNTIFS(Trades!$A$2:$A${last_row},A{i},Trades!$I$2:$I${last_row},"<=0")',
            f'=IF(B{i}=0,"n/a",C{i}/B{i})',
            f'=SUMIF(Trades!$A$2:$A${last_row},A{i},Trades!$I$2:$I${last_row})',
            f'=IFERROR(AVERAGEIF(Trades!$A$2:$A${last_row},A{i},Trades!$K$2:$K${last_row}),"n/a")',
        ]
        formats = [None, None, None, "0.0%", "+0.00000;-0.00000", "+0.00;-0.00"]
        for col_idx, (formula, fmt) in enumerate(zip(formulas, formats), start=2):
            cell = summary_ws.cell(row=i, column=col_idx, value=formula)
            cell.font = BODY_FONT
            if fmt:
                cell.number_format = fmt

        return_cell = summary_ws.cell(
            row=i, column=8, value=(s["total_return_pct"] if s["total_return_pct"] is not None else "n/a")
        )
        return_cell.font = BODY_FONT
        if isinstance(return_cell.value, float):
            return_cell.number_format = "+0.0%;-0.0%"

        dd_cell = summary_ws.cell(row=i, column=9, value=s["max_drawdown_pct"])
        dd_cell.font = BODY_FONT
        dd_cell.number_format = "0.0%"

    note = summary_ws.cell(
        row=len(results) + 3,
        column=1,
        value="* Total Return and Max Drawdown are the backtest run's own computed values (path-dependent on trade order), not spreadsheet formulas.",
    )
    note.font = Font(name="Arial", italic=True, size=9, color="6B7280")

    return wb
