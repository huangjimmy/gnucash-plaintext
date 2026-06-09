<?xml version="1.0" encoding="UTF-8"?>
<!--
  bill.xslt — Transform vendor-bill XML → HTML (Q-019)
  ====================================================
  Mirrors invoice.xslt but with the address sides swapped:
    "Bill From" = vendor (the supplier sending us the bill)
    "Bill To"   = our company (the recipient — set from book options)

  Input XML structure (see bill_to_xml() in services/bill_renderer.py):

    <bill status="paid|unpaid|draft" currency="CAD">
      <id>, <date>, <due-date>, <billing-id>, <notes>
      <vendor>    <name>, <addr1..4>, <email>
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
      <draft-tax-notice/>           (present only on unposted bills)
      <payments>
        <payment>  <date>, <num>, <memo>, <amount>
      </payments>
      <amount-remaining>            (present only on posted bills)
    </bill>

  Styling rules for the Tax Applied column:
    type="exempt"   → grey italic
    type="single"   → dark blue
    type="combined" → dark orange
-->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<xsl:output method="html" encoding="UTF-8" indent="yes" doctype-public="-//W3C//DTD HTML 4.01//EN"/>

<xsl:variable name="show-unit-column"
              select="count(/bill/entries/entry[normalize-space(action) != '']) &gt; 0"/>

<xsl:template name="label-colspan">
  <xsl:attribute name="colspan">
    <xsl:choose>
      <xsl:when test="$show-unit-column">4</xsl:when>
      <xsl:otherwise>3</xsl:otherwise>
    </xsl:choose>
  </xsl:attribute>
</xsl:template>

<xsl:template match="/bill">
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Bill <xsl:value-of select="id"/></title>
  <style>
    body        { font-family: Arial, sans-serif; font-size: 13px;
                  margin: 40px; color: #222; }
    h1          { font-size: 24px; margin: 0 0 2px; letter-spacing: 1px; }
    .inv-meta   { color: #666; font-size: 12px; margin-bottom: 24px; }

    .badge        { display: inline-block; padding: 2px 8px; border-radius: 4px;
                    font-size: 11px; font-weight: bold; text-transform: uppercase;
                    letter-spacing: 1px; margin-left: 10px; vertical-align: middle; }
    .badge-paid   { background: #d4edda; color: #155724; }
    .badge-unpaid { background: #fff3cd; color: #856404; }
    .badge-draft  { background: #e2e3e5; color: #383d41; }

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

    .addresses  { display: flex; gap: 60px; margin-bottom: 28px; }
    .addr h3    { margin: 0 0 6px; font-size: 11px; text-transform: uppercase;
                  color: #999; letter-spacing: 1px; }
    .addr p     { margin: 1px 0; }
    .addr-to    { margin-left: auto; text-align: right; }
    .co-reg     { color: #888; font-size: 11px; }

    table       { width: 100%; border-collapse: collapse; }
    thead th    { background: #f5f5f5; padding: 7px 8px; text-align: left;
                  border-top: 2px solid #ccc; border-bottom: 2px solid #ccc;
                  font-size: 11px; text-transform: uppercase; letter-spacing: .5px; }
    tbody td    { padding: 6px 8px; border-bottom: 1px solid #eee; }
    tfoot td    { padding: 6px 8px; }

    .subtotal-row td { color: #555; font-style: italic; }
    .tax-row td      { color: #555; }
    .total-row td    { font-weight: bold; font-size: 14px;
                       border-top: 2px solid #333; }

    .tax-exempt   { color: #aaa; font-style: italic; }
    .tax-single   { color: #1a5276; }
    .tax-combined { color: #b85c00; font-weight: bold; }

    .notes { margin-top: 28px; padding: 10px 14px; background: #fafafa;
             border-left: 3px solid #ccc; color: #555; font-size: 12px; }
  </style>
</head>
<body>

  <h1>
    Bill
    <xsl:choose>
      <xsl:when test="@status = 'paid'">
        <span class="badge badge-paid">Paid</span>
      </xsl:when>
      <xsl:when test="@status = 'draft'">
        <span class="badge badge-draft">Draft</span>
      </xsl:when>
      <xsl:otherwise>
        <span class="badge badge-unpaid">Unpaid</span>
      </xsl:otherwise>
    </xsl:choose>
  </h1>

  <div class="inv-meta">
    <strong>Bill #:</strong> <xsl:value-of select="id"/>
    &#160;|&#160;
    <strong>Date:</strong> <xsl:value-of select="date"/>
    <xsl:if test="string-length(due-date) > 0">
      &#160;|&#160;
      <strong>Due:</strong> <xsl:value-of select="due-date"/>
    </xsl:if>
    <xsl:if test="string-length(billing-id) > 0">
      &#160;|&#160;
      <strong>PO / Billing ID:</strong> <xsl:value-of select="billing-id"/>
    </xsl:if>
  </div>

  <!-- Address blocks. Bill From = vendor (left), Bill To = us (right). -->
  <div class="addresses">
    <div class="addr">
      <h3>Bill From</h3>
      <p><strong><xsl:value-of select="vendor/name"/></strong></p>
      <xsl:if test="string-length(vendor/addr1) > 0">
        <p><xsl:value-of select="vendor/addr1"/></p>
      </xsl:if>
      <xsl:if test="string-length(vendor/addr2) > 0">
        <p><xsl:value-of select="vendor/addr2"/></p>
      </xsl:if>
      <xsl:if test="string-length(vendor/addr3) > 0">
        <p><xsl:value-of select="vendor/addr3"/></p>
      </xsl:if>
      <xsl:if test="string-length(vendor/addr4) > 0">
        <p><xsl:value-of select="vendor/addr4"/></p>
      </xsl:if>
      <xsl:if test="string-length(vendor/email) > 0">
        <p><xsl:value-of select="vendor/email"/></p>
      </xsl:if>
    </div>

    <xsl:if test="string-length(company/name) > 0">
      <div class="addr addr-to">
        <h3>Bill To</h3>
        <p><strong><xsl:value-of select="company/name"/></strong></p>
        <xsl:if test="string-length(company/contact) > 0">
          <p>Attn: <xsl:value-of select="company/contact"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/id) > 0">
          <p class="co-reg">Company ID: <xsl:value-of select="company/id"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/gst) > 0">
          <p class="co-reg">GST: <xsl:value-of select="company/gst"/></p>
        </xsl:if>
        <xsl:for-each select="company/pst">
          <p class="co-reg">PST: <xsl:value-of select="."/></p>
        </xsl:for-each>
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
        <xsl:if test="string-length(company/fax) > 0">
          <p>Fax: <xsl:value-of select="company/fax"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/email) > 0">
          <p><xsl:value-of select="company/email"/></p>
        </xsl:if>
        <xsl:if test="string-length(company/url) > 0">
          <p><xsl:value-of select="company/url"/></p>
        </xsl:if>
      </div>
    </xsl:if>
  </div>

  <table>
    <thead>
      <tr>
        <th>Description</th>
        <xsl:if test="$show-unit-column">
          <th style="text-align:center">Unit</th>
        </xsl:if>
        <th style="text-align:right">Qty</th>
        <th style="text-align:right">Unit Price</th>
        <th style="text-align:right">Amount</th>
        <th style="text-align:center">Tax Applied</th>
      </tr>
    </thead>
    <tbody>
      <xsl:apply-templates select="entries/entry"/>

      <tr class="subtotal-row">
        <td style="text-align:right">
          <xsl:call-template name="label-colspan"/>
          <em>Subtotal</em>
        </td>
        <td style="text-align:right">
          <xsl:value-of select="concat(@currency, '&#160;')"/>
          <xsl:value-of select="format-number(subtotal, '#,##0.00')"/>
        </td>
        <td/>
      </tr>

      <xsl:apply-templates select="tax-lines/tax-line"/>

      <xsl:if test="draft-tax-notice">
        <tr class="provisional-row">
          <td>
            <xsl:call-template name="label-colspan"/>
          </td>
          <td colspan="2" style="text-align:right; font-style:italic; color:#856404; font-size:11px">
            Tax is computed from line-item tax tables; bill not yet posted &#8212; figures are provisional.
          </td>
        </tr>
      </xsl:if>
    </tbody>
    <tfoot>
      <tr class="total-row">
        <td style="text-align:right">
          <xsl:call-template name="label-colspan"/>
          Total Payable (<xsl:value-of select="@currency"/>)
        </td>
        <td style="text-align:right">
          <xsl:value-of select="concat(@currency, '&#160;')"/>
          <xsl:value-of select="format-number(total, '#,##0.00')"/>
        </td>
        <td/>
      </tr>
    </tfoot>
  </table>

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

  <xsl:if test="string-length(notes) > 0">
    <div class="notes">
      <strong>Notes:</strong> <xsl:value-of select="notes"/>
    </div>
  </xsl:if>

</body>
</html>
</xsl:template>

<xsl:template match="entry">
  <tr>
    <td><xsl:value-of select="description"/></td>
    <xsl:if test="$show-unit-column">
      <td style="text-align:center"><xsl:value-of select="action"/></td>
    </xsl:if>
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
      <xsl:variable name="ttype" select="tax-label/@type"/>
      <xsl:choose>
        <xsl:when test="$ttype = 'exempt'">
          <span class="tax-exempt"><xsl:value-of select="tax-label"/></span>
        </xsl:when>
        <xsl:when test="$ttype = 'combined'">
          <span class="tax-combined"><xsl:value-of select="tax-label"/></span>
        </xsl:when>
        <xsl:otherwise>
          <span class="tax-single"><xsl:value-of select="tax-label"/></span>
        </xsl:otherwise>
      </xsl:choose>
    </td>
  </tr>
</xsl:template>

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

<xsl:template match="tax-line">
  <tr class="tax-row">
    <td style="text-align:right">
      <xsl:call-template name="label-colspan"/>
      <xsl:value-of select="name"/>
    </td>
    <td style="text-align:right">
      $<xsl:value-of select="format-number(amount, '#,##0.00')"/>
    </td>
    <td/>
  </tr>
</xsl:template>

</xsl:stylesheet>
