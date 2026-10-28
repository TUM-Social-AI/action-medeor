from app.parsing.table_mapping import layout_issues
from app.parsing.table_parser import _find_header_row, parse_table_rows


def test_request_unit_quantity_before_supplier_block_is_not_a_supplier_field():
    header = [
        "No",
        "Code PUI",
        "Designation",
        "Unit Qty / Qté unitaire (ex: 1 comprimé, 1 ampoule etc)",
        "Supplier code / Code fournisseur",
        "Unit Price / Prix à l'unité",
        "Article priority",
        "Comments",
    ]
    rows = [
        header,
        [1, "CODE-A", "Amoxicillin 500mg", 20, "VENDOR-A", 100, "Standard", ""],
        header,
        [2, "CODE-B", "Thermometer", 5, "VENDOR-B", 250, "Standard", ""],
    ]
    assert layout_issues(rows, _find_header_row(rows)) == []
    document = parse_table_rows(rows)
    assert [item.name for item in document.items] == ["Amoxicillin 500mg", "Thermometer"]
    assert [item.quantity for item in document.items] == [20, 5]
    assert all(not item.review_source["mappingUncertain"] for item in document.items)


def test_a_product_named_like_one_header_is_not_removed():
    rows = [["Product", "Quantity", "Unit"], ["Product", 10, "pcs"], ["Gauze", 20, "pcs"]]
    assert len(parse_table_rows(rows).items) == 2
