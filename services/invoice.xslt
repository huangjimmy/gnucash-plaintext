<?xml version="1.0" encoding="UTF-8"?>
<!--
  invoice.xslt — Transform invoice XML → HTML
  ============================================
  Input XML structure (see invoice_to_xml() in test_business_roundtrip.py):

    <invoice status="paid|unpaid" currency="CAD">
      <id>, <date>, <due-date>, <billing-id>, <notes>
      <customer>  <name>, <addr1..4>, <email>, <phone>
      <company>   <name>, <id>, <addr1..4>, <phone>, <email>, <url>
      <entries>
        <entry>
          <description>, <action>, <quantity>, <unit-price>, <amount>
          <tax-label type="exempt|single|combined">…label text…</tax-label>
        </entry>
      </entries>
      <subtotal>, <total>
      <tax-lines>
        <tax-line>  <name>, <amount>
      </tax-lines>
    </invoice>

  Styling rules for the Tax Applied column:
    type="exempt"   → grey italic    (zero-rated / no tax)
    type="single"   → dark blue      (one tax, e.g. GST only or HST)
    type="combined" → dark orange    (two or more taxes, e.g. GST + PST)

  To change styles, edit the <style> block below — no Python changes needed.
-->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<xsl:output method="html" encoding="UTF-8" indent="yes" doctype-public="-//W3C//DTD HTML 4.01//EN"/>

<!-- ═══════════════════════════════════════════════════════════════════════
     Root template
     ═══════════════════════════════════════════════════════════════════════ -->
<xsl:template match="/invoice">
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Invoice <xsl:value-of select="id"/></title>
  <style>
    /* ── Page layout ──────────────────────────────────────────────── */
    body        { font-family: Arial, sans-serif; font-size: 13px;
                  margin: 40px; color: #222; }
    h1          { font-size: 24px; margin: 0 0 2px; letter-spacing: 1px; }
    .inv-meta   { color: #666; font-size: 12px; margin-bottom: 24px; }

    /* ── Status badge ─────────────────────────────────────────────── */
    .badge        { display: inline-block; padding: 2px 8px; border-radius: 4px;
                    font-size: 11px; font-weight: bold; text-transform: uppercase;
                    letter-spacing: 1px; margin-left: 10px; vertical-align: middle; }
    .badge-paid   { background: #d4edda; color: #155724; }
    .badge-unpaid { background: #fff3cd; color: #856404; }

    /* ── Payment history section ───────────────────────────────────── */
    .payment-section { margin-top: 28px; }
    .payment-section h3 { font-size: 11px; text-transform: uppercase;
                          letter-spacing: 1px; color: #999; margin: 0 0 6px; }
    .payment-section table { margin-top: 0; }
    .pay-row td  { padding: 4px 8px; border-bottom: 1px solid #eee;
                   font-size: 12px; color: #444; }
    .pay-num     { color: #888; font-size: 11px; }
    .remaining-row td { padding: 6px 8px; font-weight: bold;
                        border-top: 2px solid #333; }
    .remaining-paid   { color: #155724; }
    .remaining-due    { color: #856404; }

    /* ── Addresses ────────────────────────────────────────────────── */
    .addresses  { display: flex; gap: 60px; margin-bottom: 28px; }
    .addr h3    { margin: 0 0 6px; font-size: 11px; text-transform: uppercase;
                  color: #999; letter-spacing: 1px; }
    .addr p     { margin: 1px 0; }
    .addr-from  { margin-left: auto; text-align: right; }
    .co-reg     { color: #888; font-size: 11px; }

    /* ── Line-items table ─────────────────────────────────────────── */
    table       { width: 100%; border-collapse: collapse; }
    thead th    { background: #f5f5f5; padding: 7px 8px; text-align: left;
                  border-top: 2px solid #ccc; border-bottom: 2px solid #ccc;
                  font-size: 11px; text-transform: uppercase; letter-spacing: .5px; }
    tbody td    { padding: 6px 8px; border-bottom: 1px solid #eee; }
    tfoot td    { padding: 6px 8px; }

    /* ── Subtotal / tax rows ──────────────────────────────────────── */
    .subtotal-row td { color: #555; font-style: italic; }
    .tax-row td      { color: #555; }
    .total-row td    { font-weight: bold; font-size: 14px;
                       border-top: 2px solid #333; }

    /* ── Tax-applied column colours ──────────────────────────────── */
    /* Change these three rules to restyle the Tax Applied column     */
    .tax-exempt   { color: #aaa; font-style: italic; }          /* zero-rated   */
    .tax-single   { color: #1a5276; }                            /* one tax      */
    .tax-combined { color: #b85c00; font-weight: bold; }         /* GST + PST/QST */

    /* ── Notes ───────────────────────────────────────────────────── */
    .notes { margin-top: 28px; padding: 10px 14px; background: #fafafa;
             border-left: 3px solid #ccc; color: #555; font-size: 12px; }
  </style>
</head>
<body>

  <!-- Invoice title + status badge -->
  <h1>
    Invoice
    <xsl:choose>
      <xsl:when test="@status = 'paid'">
        <span class="badge badge-paid">Paid</span>
      </xsl:when>
      <xsl:otherwise>
        <span class="badge badge-unpaid">Unpaid</span>
      </xsl:otherwise>
    </xsl:choose>
  </h1>

  <div class="inv-meta">
    <strong>Invoice #:</strong> <xsl:value-of select="id"/>
    &#160;|&#160;
    <strong>Date:</strong> <xsl:value-of select="date"/>
    &#160;|&#160;
    <strong>Due:</strong> <xsl:value-of select="due-date"/>
    <xsl:if test="string-length(billing-id) > 0">
      &#160;|&#160;
      <strong>PO / Billing ID:</strong> <xsl:value-of select="billing-id"/>
    </xsl:if>
  </div>

  <!-- Bill-to / From addresses -->
  <div class="addresses">
    <!-- Bill To (customer) -->
    <div class="addr">
      <h3>Bill To</h3>
      <p><strong><xsl:value-of select="customer/name"/></strong></p>
      <xsl:if test="string-length(customer/addr1) > 0">
        <p><xsl:value-of select="customer/addr1"/></p>
      </xsl:if>
      <xsl:if test="string-length(customer/addr2) > 0">
        <p><xsl:value-of select="customer/addr2"/></p>
      </xsl:if>
      <xsl:if test="string-length(customer/addr3) > 0">
        <p><xsl:value-of select="customer/addr3"/></p>
      </xsl:if>
      <xsl:if test="string-length(customer/addr4) > 0">
        <p><xsl:value-of select="customer/addr4"/></p>
      </xsl:if>
      <xsl:if test="string-length(customer/email) > 0">
        <p><xsl:value-of select="customer/email"/></p>
      </xsl:if>
    </div>

    <!-- From (seller / company) — shown only when company name is present -->
    <xsl:if test="string-length(company/name) > 0">
      <div class="addr addr-from">
        <h3>From</h3>
        <p><strong><xsl:value-of select="company/name"/></strong></p>
        <xsl:if test="string-length(company/id) > 0">
          <p class="co-reg">GST/HST Reg: <xsl:value-of select="company/id"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/addr1) > 0">
          <p><xsl:value-of select="company/addr1"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/addr2) > 0">
          <p><xsl:value-of select="company/addr2"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/addr3) > 0">
          <p><xsl:value-of select="company/addr3"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/addr4) > 0">
          <p><xsl:value-of select="company/addr4"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/phone) > 0">
          <p><xsl:value-of select="company/phone"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/email) > 0">
          <p><xsl:value-of select="company/email"/></p>
        </xsl:if>
      </div>
    </xsl:if>
  </div>

  <!-- Line-items table -->
  <table>
    <thead>
      <tr>
        <th>Description</th>
        <th style="text-align:center">Unit</th>
        <th style="text-align:right">Qty</th>
        <th style="text-align:right">Unit Price</th>
        <th style="text-align:right">Amount</th>
        <th style="text-align:center">Tax Applied</th>
      </tr>
    </thead>
    <tbody>
      <xsl:apply-templates select="entries/entry"/>

      <!-- Subtotal row -->
      <tr class="subtotal-row">
        <td colspan="4" style="text-align:right"><em>Subtotal</em></td>
        <td style="text-align:right">
          <xsl:value-of select="concat(@currency, '&#160;')"/>
          <xsl:value-of select="format-number(subtotal, '#,##0.00')"/>
        </td>
        <td/>
      </tr>

      <!-- Tax lines -->
      <xsl:apply-templates select="tax-lines/tax-line"/>
    </tbody>
    <tfoot>
      <tr class="total-row">
        <td colspan="4" style="text-align:right">Total Due (<xsl:value-of select="@currency"/>)</td>
        <td style="text-align:right">
          <xsl:value-of select="concat(@currency, '&#160;')"/>
          <xsl:value-of select="format-number(total, '#,##0.00')"/>
        </td>
        <td/>
      </tr>
    </tfoot>
  </table>

  <!-- Payment history -->
  <xsl:if test="payments/payment">
    <div class="payment-section">
      <h3>Payment History</h3>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Reference</th>
            <th>Memo</th>
            <th style="text-align:right">Amount Paid</th>
          </tr>
        </thead>
        <tbody>
          <xsl:apply-templates select="payments/payment"/>
          <tr class="remaining-row">
            <td colspan="3" style="text-align:right">Amount Remaining</td>
            <td style="text-align:right">
              <xsl:choose>
                <xsl:when test="number(amount-remaining) = 0">
                  <span class="remaining-paid">
                    <xsl:value-of select="@currency"/>&#160;0.00&#160;&#10003;
                  </span>
                </xsl:when>
                <xsl:otherwise>
                  <span class="remaining-due">
                    <xsl:value-of select="@currency"/>&#160;<xsl:value-of select="format-number(amount-remaining, '#,##0.00')"/>
                  </span>
                </xsl:otherwise>
              </xsl:choose>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </xsl:if>

  <!-- Notes -->
  <xsl:if test="string-length(notes) > 0">
    <div class="notes">
      <strong>Notes:</strong> <xsl:value-of select="notes"/>
    </div>
  </xsl:if>

</body>
</html>
</xsl:template>

<!-- ═══════════════════════════════════════════════════════════════════════
     Line-item entry row
     ═══════════════════════════════════════════════════════════════════════ -->
<xsl:template match="entry">
  <tr>
    <td><xsl:value-of select="description"/></td>
    <td style="text-align:center"><xsl:value-of select="action"/></td>
    <td style="text-align:right">
      <xsl:value-of select="format-number(quantity, '#,##0.##')"/>
    </td>
    <td style="text-align:right">
      $<xsl:value-of select="format-number(unit-price, '#,##0.00')"/>
    </td>
    <td style="text-align:right">
      $<xsl:value-of select="format-number(amount, '#,##0.00')"/>
    </td>
    <td style="text-align:center; font-size:11px">
      <!-- Colour class is driven by the type attribute on <tax-label> -->
      <xsl:variable name="ttype" select="tax-label/@type"/>
      <xsl:choose>
        <xsl:when test="$ttype = 'exempt'">
          <span class="tax-exempt"><xsl:value-of select="tax-label"/></span>
        </xsl:when>
        <xsl:when test="$ttype = 'combined'">
          <span class="tax-combined"><xsl:value-of select="tax-label"/></span>
        </xsl:when>
        <xsl:otherwise>
          <!-- single or anything else -->
          <span class="tax-single"><xsl:value-of select="tax-label"/></span>
        </xsl:otherwise>
      </xsl:choose>
    </td>
  </tr>
</xsl:template>

<!-- ═══════════════════════════════════════════════════════════════════════
     Payment history row
     ═══════════════════════════════════════════════════════════════════════ -->
<xsl:template match="payment">
  <tr class="pay-row">
    <td><xsl:value-of select="date"/></td>
    <td class="pay-num"><xsl:value-of select="num"/></td>
    <td><xsl:value-of select="memo"/></td>
    <td style="text-align:right">
      $<xsl:value-of select="format-number(amount, '#,##0.00')"/>
    </td>
  </tr>
</xsl:template>

<!-- ═══════════════════════════════════════════════════════════════════════
     Tax summary row
     ═══════════════════════════════════════════════════════════════════════ -->
<xsl:template match="tax-line">
  <tr class="tax-row">
    <td colspan="4" style="text-align:right">
      <xsl:value-of select="name"/>
    </td>
    <td style="text-align:right">
      $<xsl:value-of select="format-number(amount, '#,##0.00')"/>
    </td>
    <td/>
  </tr>
</xsl:template>

</xsl:stylesheet>
