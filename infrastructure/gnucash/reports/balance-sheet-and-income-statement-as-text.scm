;; The balance sheet and income statement printed as plain text, by GnuCash
;; reports customized from GnuCash's own Balance Sheet and Income Statement.
;;
;; `balance-sheet`, `income-statement` and `report` load this file and run one
;; of these two reports for `--output-format text` (Q-042), so every figure on
;; the page is added up and converted by GnuCash, not by gnucash-plaintext.
;; Each is a GnuCash report like any other: registered with
;; `gnc:define-report`, run by GnuCash's report code, and handed GnuCash's own
;; options, because its options generator is the Balance Sheet's or the Income
;; Statement's, found by guid.
;;
;; The figures come from the calls GnuCash's own balance-sheet.scm and
;; income-statement.scm make, in the same order: each account's balance from
;; the engine, added up in GnuCash's commodity collectors, and converted by
;; `gnc:case-exchange-fn` at the report's price source. Only the page is
;; different. A renderer may return a string, and `gnc:report-render-html`
;; then returns that string unchanged, with no style sheet and no HTML. Read
;; on GnuCash 3.4, 3.8, 4.4 and 5.10.
;;
;; **Writing the figure is the one step that is not GnuCash's own call, and
;; the reason is the format.** GnuCash writes one with `gnc:monetary->string`,
;; which is `xaccPrintAmount` under `gnc-commodity-print-info`: that puts the
;; currency's symbol in front and thousands separators inside, so its own page
;; reads `C$99,996,200.00` and `JP¥250,000`. A figure on this page is read
;; back by `import`, and neither a symbol nor a separator survives that. So
;; `plaintext:figure` writes it instead — exactly, never rounded, and as a
;; fraction where no decimal states it, which is how `share_price:` carries
;; `316211/229006`.
;;
;; What that leaves GnuCash's is the decision, and this file asks for it
;; rather than choosing: how many places a figure is padded to comes from
;; `gnc-commodity-get-fraction`, through `plaintext:places-of`. Measured
;; against GnuCash's own page on the same book, by
;; `tests/research/what_gnucashs_own_report_renders_a_figure_as_probe.py`: the
;; yen is written `250000` beside its Canadian cost `2500.00`, because a yen
;; divides into 1 and a Canadian dollar into 100. Two decimal places assumed
;; anywhere here would be wrong about the yen, and a Korean won divided into
;; 100 until GnuCash 5.15.
;;
;; One file for every supported GnuCash. Options are read with
;; `gnc-optiondb-lookup-value` where the build has it (5.x) and with
;; `gnc:lookup-option` where it does not, and collectors are added with
;; 'merge and 'minusmerge, because `gnc:collector+` is absent on 3.4.

(define plaintext:balance-sheet-template "c4173ac99b2b448289bf4d11c731af13")
(define plaintext:income-statement-template "0b81a3bdfd504aff849ec2e8630524bc")

;; GnuCash's own options for the report `template`, asked for when a report is
;; made rather than when this file is loaded.
(define (plaintext:options-of template)
  (lambda ()
    ((gnc:report-template-options-generator
      (gnc:find-report-template template)))))

(define (plaintext:option report-obj section name)
  (let ((options (gnc:report-options report-obj)))
    (if (defined? 'gnc-optiondb-lookup-value)
        (gnc-optiondb-lookup-value options section name)
        (gnc:option-value (gnc:lookup-option options section name)))))

;; `Parent account subtotals` holds 't or 'f.
(define (plaintext:subtotal-mode value)
  (case value
    ((t) #t)
    ((f) #f)
    (else value)))

;; A new collector holding the sum of `collectors`.
(define (plaintext:collector . collectors)
  (let ((total (gnc:make-commodity-collector)))
    (for-each (lambda (collector) (total 'merge collector #f)) collectors)
    total))

;; `account-list-balance` in balance-sheet.scm.
(define (plaintext:balance-as-of accounts moment)
  (let ((total (gnc:make-commodity-collector)))
    (for-each (lambda (account)
                (total 'add (xaccAccountGetCommodity account)
                       (xaccAccountGetBalanceAsOfDate account moment)))
              accounts)
    total))

;; The page is written in the plaintext format this tool reads and writes: a
;; block opened by a dated directive, keys indented under it with tabs, and an
;; account written as its full path, its amount and its commodity — the shape a
;; transaction's splits are written in.
;;
;; Each account's line is what that account itself holds, so a section's total
;; is the sum of the lines under its path rather than a figure written on the
;; parent — which is how GnuCash's own page reports it, the parent's row being
;; its own balance and the total a row of its own. A figure GnuCash computes
;; that no account holds is a key of the block.
(define (plaintext:indent depth)
  (make-string depth #\tab))

(define (plaintext:key depth name value)
  (string-append (plaintext:indent depth) name ": \"" value "\""))

(define (plaintext:account-line depth full-name amount)
  (string-append (plaintext:indent depth) full-name " " amount))

;; The path this format writes: the account's names from the root down, joined
;; with colons. Not `gnc-account-get-full-name`, which joins with the book's
;; own separator — a dot in these images — and would write a path no ledger
;; could read back.
(define (plaintext:full-name account)
  (let loop ((account account) (parts '()))
    (let ((parent (gnc-account-get-parent account)))
      (if (or (not parent) (null? parent))
          (string-join parts ":")
          (loop parent (cons (xaccAccountGetName account) parts))))))

;; The decimal places that state a figure with this denominator exactly, or #f
;; where no number of them does.
(define (plaintext:decimals denom)
  (let loop ((d denom) (twos 0) (fives 0))
    (cond ((= d 1) (max twos fives))
          ((zero? (remainder d 2)) (loop (quotient d 2) (+ twos 1) fives))
          ((zero? (remainder d 5)) (loop (quotient d 5) twos (+ fives 1)))
          (else #f))))

;; What GnuCash's figure is, as an exact rational. A `gnc-numeric` is a
;; numerator over a denominator, so it is one already; a price chained through
;; a third currency has been multiplied out here and arrives as one.
(define (plaintext:exact value)
  (if (number? value)
      value
      (/ (gnc-numeric-num value) (gnc-numeric-denom value))))

;; A figure as the format writes one, exactly: never rounded, because what is
;; written here is GnuCash's own figure and rounding it would state a number
;; GnuCash did not state. Padded to the commodity's own places, and written as
;; a fraction where no decimal states it exactly — as `value:` and
;; `share_price:` are written on a split.
(define (plaintext:figure value least)
  (let* ((exact (plaintext:exact value))
         (bottom (denominator exact))
         (places (plaintext:decimals bottom)))
    (if (not places)
        (string-append (number->string (numerator exact)) "/" (number->string bottom))
        (let* ((want (max places least))
               (scaled (/ (* (numerator exact) (expt 10 want)) bottom))
               (size (abs scaled))
               (unit (expt 10 want)))
          (string-append
           (if (negative? scaled) "-" "")
           (number->string (quotient size unit))
           (if (zero? want)
               ""
               (string-append "." (string-pad (number->string (remainder size unit))
                                              want #\0))))))))

(define (plaintext:places-of commodity)
  (let ((fraction (gnc-commodity-get-fraction commodity)))
    (or (plaintext:decimals (if (and fraction (> fraction 0)) fraction 1)) 0)))

;; The same, where the book's commodity table returned nothing for a currency
;; the cost bases name. The report's own commodity answers instead, which is
;; the fallback those figures already take.
(define (plaintext:places-or report commodity)
  (plaintext:places-of (or commodity report)))

(define (plaintext:amount monetary)
  (let ((commodity (gnc:gnc-monetary-commodity monetary)))
    (string-append (plaintext:figure (gnc:gnc-monetary-amount monetary)
                                     (plaintext:places-of commodity))
                   " "
                   (gnc-commodity-get-mnemonic commodity))))

;; The same, for a figure this report worked out itself and holds as an exact
;; rational rather than as one of GnuCash's monetaries.
(define (plaintext:amount-of figure commodity)
  (string-append (plaintext:figure figure (plaintext:places-of commodity))
                 " "
                 (gnc-commodity-get-mnemonic commodity)))

;; A rational as money: at the smallest unit the commodity itself divides into.
;;
;; A price is a rate and may be exact — 189557/136000 — but a gain is an
;; amount, and multiplying a rate by a balance lands between units. Left as the
;; rational it comes to, the page printed `-993/136 CAD`, which is not a figure
;; any account can hold.
;;
;; The unit is read from the commodity, never two decimal places assumed: a
;; Japanese yen divides into 1, and a Korean won into 100 until GnuCash 5.15.
;;
;; Rounded by GnuCash, not by arithmetic of our own that imitates it. This page
;; states GnuCash's figures, so where it rounds money it has to round the way
;; GnuCash rounds money, and GnuCash exports that rule: `gnc-numeric-convert`
;; with `GNC-RND-ROUND`, which sends a tie to the nearest even. Its own report
;; code calls it — `report-utilities.scm` on 3.4, `commodity-utilities.scm` on
;; 5.10 — and so does this.
;;
;; Hand-rolled half-up instead, the two parted on a figure landing exactly on a
;; half cent: 1,000.00 USD at 1.386465 is 1386.465, which GnuCash converts to
;; 1386.46 and half-up makes 1386.47. The account line then read
;; `value: "1386.46"` while the working three lines below read `worth 1386.47`,
;; and the gain built on it left `total_liabilities_and_equity` a cent above
;; `total_assets` — on the simplest book this report draws.
;;
;; No magnitude-and-sign dance here, unlike `to_money` on the Python side. That
;; one exists because GnuCash 3.4 drops the sign of a negative exact half under
;; `GNC_HOW_RND_ROUND_HALF_UP` (CLAUDE.md finding 22). Measured on 3.4 and
;; 5.10, `GNC-RND-ROUND` keeps it: -13.865 comes back -693/50 on both.
;;
;; GnuCash's rule, applied here rather than called, and only because its own
;; function cannot be handed these figures. `gnc-numeric-create` takes two
;; `gint64`, and a cost summed across several part-drawn bases outgrows that: a
;; cost is a value over an amount, so a basis drawn part of the way carries a
;; denominator about the size of its amount in cents, and three of them
;; multiply out to a numerator near 5e20 where `INT64_MAX` is about 9.2e18.
;; Measured on 3.4 and 5.10 alike, the engine answers `Value out of range
;; -9223372036854775808 to 9223372036854775807` and the page does not render at
;; all — on a book whose cost bases match its holdings, which is the book this
;; feature is for.
;;
;; Guile's `round` on an exact rational is the same tie rule — to the nearest
;; even — and has no ceiling. So the rule is still GnuCash's, and
;; `test_the_report_rounds_the_way_gnucash_rounds.py` asks GnuCash itself what
;; that rule answers so that a change in it would be caught here rather than
;; assumed. What is not GnuCash's is the arithmetic, because the arithmetic has
;; to hold numbers GnuCash's own arguments cannot.
(define (plaintext:as-money figure commodity)
  (let* ((fraction (gnc-commodity-get-fraction commodity))
         (unit (if (and fraction (> fraction 0)) fraction 1)))
    (/ (round (* (inexact->exact figure) unit)) unit)))

;; What the foreign money the book still holds cost, in the report's currency,
;; one row per cost basis as `(currency quantity spent side)` with the owed
;; side's figures negative. Empty until somebody sets the cost basis items it is
;; derived from, and the balance sheet then falls back to GnuCash's own
;; reconstruction.
;;
;; Derived rather than sent, because it is the same data as
;; `plaintext:cost-basis-items` in another shape, and this page exists to show
;; that a key and the items under it agree. Serialised twice, the two could come
;; from different reads of the book and disagree — which is the very fault the
;; itemized page was printing before, a key and its items stating different
;; figures. One list, read once, and every figure on the page traceable to it.
(define (plaintext:cost-bases)
  (map (lambda (item)
         (let* ((side (plaintext:basis-item-side item))
                (sign (if (string=? side "asset") 1 -1))
                (balance (plaintext:basis-item-balance item)))
           (list (plaintext:basis-item-currency item)
                 (* sign balance)
                 (* sign balance (plaintext:basis-item-cost item))
                 side
                 (plaintext:basis-item-namespace item)
                 (* sign (plaintext:basis-item-cost-held item)))))
       plaintext:cost-basis-items))

;; What the book has already taken on foreign currency by the report's date, in
;; the book's own currency. A disposal values what it sells at what that
;; currency cost, so the splits beside it state what it fetched and the
;; difference is what was made or lost — gnucash-plaintext sums that and calls
;; `plaintext:set-realized-fx!` before the report runs.
;;
;; Stated on the page and added into nothing: it is inside `retained_earnings`
;; already, having gone through the income statement, and adding it to
;; `total_equity` a second time is what leaves equity standing against assets
;; that are gone.
;;
;; Zero where nothing set it — GnuCash's own report chooser, or a build of this
;; file run by hand — which is also the right figure for a book that has
;; disposed of no foreign currency at all.
(define plaintext:realized-fx 0)

(define (plaintext:set-realized-fx! figure)
  (set! plaintext:realized-fx figure))

;; Whether the page shows how each gain figure was worked out.
;;
;; On by default, and that is the point of it: a reader can check an account
;; line against their own book and a section total by adding the lines above
;; it, but a gain is measured against costs that are on no line of the page. A
;; total nobody can reproduce is a total nobody should trust, so the page shows
;; its working — what the book holds of each currency, what that cost, what it
;; is worth at the price nearest this date, and the difference — and GnuCash's
;; own arithmetic beside it, commodity by commodity.
;;
;; Written as keys indented under the one they explain, the way `share_price:`
;; and `value:` are indented under an account line, each line stating its own
;; arithmetic in a trailing `#` comment.
(define plaintext:itemize? #t)

(define (plaintext:set-itemize! shown)
  (set! plaintext:itemize? shown))

;; How many entries a list under a gain figure may show. **-1 is no cap, and is
;; the default**; 0 lists none of them; every other number means itself.
;;
;; Zero was the sentinel for "all" first, and it read backwards — a page said
;; `--max-items 0 for all`, asking a reader to learn that nought meant
;; everything. Each value now says what it does, and 0 is the useful thing it
;; looks like: a key's totals with none of its entries under them.
;;
;; **A shortened list still carries what it left out, as one more entry.** The
;; items are there so that a reader can add a total up for themselves, and each
;; of those totals states in its own comment that it is their sum — so a list
;; that simply stopped after five made its own comment untrue, and left a
;; reader adding five figures that come to less than the total printed beneath
;; them. `not_listed:` holds the count and what the rest come to, and the
;; arithmetic closes again.
;;
;; Measured before any of this existed, by
;; `tests/research/how_a_page_grows_with_the_splits_behind_it_probe.py`: a book
;; of 2,500 purchases draws 40,154 lines and 1.4 MB, of which 40,069 lines are
;; the four itemized keys. That is about sixteen lines a transaction, and
;; nothing capped any of it.
;;
;; Grouping the entries was tried first and does not work. On a book whose
;; purchases differ from one another — its own amount, rate and date each time,
;; which is what a real book is — 2,500 cost bases fall into 2,500 distinct
;; account-and-price groups, so rolling them up shortens nothing at all. The
;; earlier measurement that said otherwise had bought the same 1.00 USD at 1.30
;; two and a half thousand times: its entries were identical for want of
;; variety in the fixture, not for anything about the format.
;;
;; So the only thing that shortens such a page is leaving entries out, which is
;; asked for rather than applied — and where it bites, the list's own line says
;; how many there are and the entry beneath them carries the rest.
(define plaintext:max-items -1)

(define (plaintext:set-max-items! count)
  (set! plaintext:max-items count))

;; Whether one more entry is listed, counting how many have been listed already.
(define (plaintext:room-for? shown)
  (or (negative? plaintext:max-items) (< shown plaintext:max-items)))

;; The first `plaintext:max-items` of a list, or all of it where no cap is set.
(define (plaintext:first-of items)
  (if (negative? plaintext:max-items)
      items
      (let take ((rest items) (room plaintext:max-items) (out '()))
        (if (or (null? rest) (= room 0))
            (reverse out)
            (take (cdr rest) (- room 1) (cons (car rest) out))))))

;; The rest of the same list: what the cap left out, in order.
(define (plaintext:after-first items)
  (if (negative? plaintext:max-items)
      '()
      (let drop ((rest items) (room plaintext:max-items))
        (cond ((null? rest) '())
              ((= room 0) rest)
              (else (drop (cdr rest) (- room 1)))))))

;; How many of `total` entries the cap left out, and zero where it left none.
(define (plaintext:left-out total)
  (if (or (negative? plaintext:max-items) (<= total plaintext:max-items))
      0
      (- total plaintext:max-items)))

;; What a list's own line says about what is under it: the empty note where
;; there is nothing, nothing at all where the list is whole, and where the cap
;; bit, how many entries there are and where the rest of them went.
;; `noun` is the plural and `one` the singular, because a cap of 0 on a list of
;; one writes this note and "1 commodities" is not a sentence.
(define (plaintext:listing-note total noun one empty-note)
  (cond ((= total 0) empty-note)
        ((= (plaintext:left-out total) 0) "")
        (else (string-append " # " (number->string total) " "
                             (if (= total 1) one noun) ", "
                             (number->string plaintext:max-items)
                             " listed and the rest under not_listed;"
                             " --max-items -1 for all"))))

;; The entry a shortened list ends with: how many entries it left out, and what
;; those come to, one figure per additive field of the entries above it. What
;; it is for is the arithmetic — with it, the listed entries and this one add
;; up to the total printed beneath them, which is what that total's own comment
;; says of it.
;;
;; The fields it carries are the ones that add. A guid, an account and a price
;; differ from one entry to the next and have no sum, so they are not here: a
;; reader wanting those asks for the entries themselves.
(define (plaintext:not-listed depth count figures)
  (append
   (list (string-append (plaintext:indent depth) "not_listed:")
         (string-append (plaintext:indent (+ depth 1)) "count: "
                        (number->string count)))
   (map (lambda (figure)
          (string-append (plaintext:indent (+ depth 1))
                         (car figure) ": " (cdr figure)))
        figures)))

;; Whether the realized figure was computed at all. It is summed from what each
;; disposal's `$residual$` split came to in the book's own currency, and every
;; cost this tool records is in that currency — so a page asked for in another
;; one has nothing to sum, and gnucash-plaintext hands over a zero meaning "not
;; measured". Printed, that zero reads as a fact: a book that realized 100.00
;; CAD stated `realized_gains_fx: 0.00 USD` when its page was asked for in US
;; dollars. So the two realized keys are left off instead, the way a
;; trading-accounts book leaves off all of them — a key states something the
;; book has, and absence is the honest answer where nothing was worked out.
(define plaintext:realized-known? #t)

;; Whether the book keeps cost bases (Q-049). A book whose `company` block says
;; `cost_bases: "off"` has none, so every currency and security it holds is
;; measured from GnuCash's revaluation, and the page says that is why rather
;; than that its cost bases disagree with its accounts.
(define plaintext:keeps-cost-bases? #t)

(define (plaintext:set-keeps-cost-bases! keeps)
  (set! plaintext:keeps-cost-bases? keeps))

(define (plaintext:why-measured-from-revaluation)
  (if plaintext:keeps-cost-bases?
      " # its cost bases do not account for what the accounts hold"
      " # this book keeps no cost bases"))

(define (plaintext:set-realized-known! known)
  (set! plaintext:realized-known? known))

;; Each exchange difference the book has realized by the report's date, as
;; `(date account figure)`, oldest first — what `plaintext:realized-fx` totals.
;; The page lists them so the total can be checked against the transactions it
;; came from. Empty until somebody sets it, which is also the right answer for
;; a book that has realized nothing.
(define plaintext:realized-items '())

(define (plaintext:set-realized-items! items)
  (set! plaintext:realized-items items))

;; The same two for a gain taken on a security rather than on a currency. Kept
;; apart all the way to the page because they are two figures a reader needs
;; separately: a return asks what was made on shares and what was made on
;; currency, and a program reading gnucash-plaintext's pages may handle
;; currency and not securities.
(define plaintext:realized-other 0)

(define (plaintext:set-realized-other! figure)
  (set! plaintext:realized-other figure))

(define plaintext:realized-other-items '())

(define (plaintext:set-realized-other-items! items)
  (set! plaintext:realized-other-items items))

;; Every cost basis as its own row, `(guid account currency side namespace
;; balance cost cost-in-pair cost-rate pair-currency)`. This is the one list the
;; page receives, and `plaintext:cost-bases` is derived from it below: whatever
;; reads either groups by currency and side rather than receiving them grouped.
;;
;; The last three say what the cost is made of: the price a unit was traded at
;; in the currency the transaction was stated in, the rate from that currency
;; into the book's, and which currency that is. Multiplied out they are `cost`.
(define plaintext:cost-basis-items '())

(define (plaintext:set-cost-basis-items! items)
  (set! plaintext:cost-basis-items items))

(define (plaintext:basis-item-guid item) (car item))
(define (plaintext:basis-item-account item) (car (cdr item)))
(define (plaintext:basis-item-currency item) (car (cdr (cdr item))))
(define (plaintext:basis-item-side item) (car (cdr (cdr (cdr item)))))
(define (plaintext:basis-item-namespace item) (car (cdr (cdr (cdr (cdr item))))))
(define (plaintext:basis-item-balance item)
  (list-ref item 5))
(define (plaintext:basis-item-cost item)
  (list-ref item 6))
(define (plaintext:basis-item-cost-in-pair item)
  (list-ref item 7))
(define (plaintext:basis-item-cost-rate item)
  (list-ref item 8))
(define (plaintext:basis-item-pair-currency item)
  (list-ref item 9))
;; What the book still holds of the basis's cost: what it cost less what its
;; disposals were valued at, worked out by `cost_basis_items_by_currency_and_side`.
(define (plaintext:basis-item-cost-held item)
  (list-ref item 10))

;; The distinct currency and side pairs those rows cover, in the order they
;; first appear. US dollars never meet Hong Kong dollars, and a currency held
;; and owed at once keeps its two sides apart.
(define (plaintext:cost-basis-pairs)
  (let loop ((rest plaintext:cost-basis-items) (found '()))
    (if (null? rest)
        (reverse found)
        (let ((cur (plaintext:basis-item-currency (car rest)))
              (sde (plaintext:basis-item-side (car rest))))
          (loop (cdr rest)
                (if (let seen ((xs found))
                      (cond ((null? xs) #f)
                            ((and (string=? (car (car xs)) cur)
                                  (string=? (cdr (car xs)) sde)) #t)
                            (else (seen (cdr xs)))))
                    found
                    (cons (cons cur sde) found)))))))

;; `realized_gains_fx` with the differences it is made of under it: whether the
;; figure was worked out at all, the figure, then one `split:` per difference
;; stating the day it was taken, the account it was booked to and what it came
;; to. Q-044 fixes the shape.
;;
;; No `realized-available:` key. It could only ever say `yes`: the one caller
;; is inside `(if plaintext:realized-known? … '())`, so where the figure was not
;; worked out this block is not written at all and the whole
;; `realized_gains_fx` / `realized_gains_other` / `total_realized_gains` group
;; is absent. A key whose only value is the one a reader can read off the key's
;; own presence tells them nothing, and its `no` was a branch nothing could
;; reach. It was also the page's only hyphenated key, beside
;; `cost_basis_balance`, `sum_value` and the rest.
(define (plaintext:realized-block report-commodity)
  (append
   (list (string-append (plaintext:indent 1) "realized_gains_fx:")
         (string-append (plaintext:indent 2) "realized_gains_fx: "
                        (plaintext:figure plaintext:realized-fx
                                          (plaintext:places-of report-commodity)))
         (string-append (plaintext:indent 2) "splits:"
                        (plaintext:listing-note
                         (length plaintext:realized-items) "splits" "split"
                         " # there is no split")))
   (let loop ((items (plaintext:first-of plaintext:realized-items)) (lines '()))
     (if (null? items)
         lines
         (let ((item (car items)))
           (loop (cdr items)
                 (append
                  lines
                  (list (string-append (plaintext:indent 3) "split:")
                        (string-append (plaintext:indent 4) "date: " (car item))
                        ;; Quoted, as `account:` is in a cost basis entry and in
                        ;; a balancing group. One key, one shape, wherever it
                        ;; appears: an account path may hold a space, and a
                        ;; reader parsing one form of this key should not meet
                        ;; two.
                        (string-append (plaintext:indent 4) "account: \""
                                       (car (cdr item)) "\"")
                        (string-append
                         (plaintext:indent 4) "amount: "
                         (plaintext:figure (car (cdr (cdr item)))
                                           (plaintext:places-of report-commodity)))))))))
   (let ((left-out (plaintext:after-first plaintext:realized-items)))
     (if (null? left-out)
         '()
         (plaintext:not-listed
          3 (length left-out)
          (list (cons "amount"
                      (plaintext:figure
                       (let sum ((items left-out) (total 0))
                         (if (null? items)
                             total
                             (sum (cdr items)
                                  (+ total (car (cdr (cdr (car items))))))))
                       (plaintext:places-of report-commodity)))))))))

;; How much of `commodity` the accounts passed hold at `moment`.
;;
;; One side's accounts, never both: the balance sheet states a gain for the
;; currency it holds and for the currency it owes separately, and each side's
;; cost bases are checked against the holdings of that side alone. Handed both
;; at once a bank and a loan would net against each other, and a book holding
;; 7,480.00 USD against 2,500.00 USD owed would answer 4,980.00 — a figure
;; neither side's cost bases account for, so neither would match and both would
;; fall back to GnuCash's revaluation.
;; The accounts whose balance at `moment` is on this side of the sheet: an
;; asset account below zero owes its currency and a liability account above
;; zero holds it (Q-047). So a US dollar bank at -500.00 is counted with the
;; owed side, where the cost basis it opened sits, and not against the held
;; side's cost bases. Counted by type, it took 500.00 off what the held side
;; holds, neither side matched its cost bases, and both fell back to GnuCash's
;; revaluation.
;;
;; A receivable or a payable stays on its type's side: its lots keep a posting
;; apart from a credit, and its balance is the two added together. So does an
;; account holding shares: a share account below zero is not shares owed, and
;; the import reads currency alone past zero.
(define (plaintext:on-the-side-of-its-balance side asset-accounts
                                              liability-accounts moment)
  (define (stays-on-its-types-side? account)
    (let ((commodity (xaccAccountGetCommodity account)))
      (or (memv (xaccAccountGetType account)
                (list ACCT-TYPE-RECEIVABLE ACCT-TYPE-PAYABLE))
          (not commodity)
          (not (string=? (gnc-commodity-get-namespace commodity) "CURRENCY")))))
  (define (balance account)
    (plaintext:exact (xaccAccountGetBalanceAsOfDate account moment)))
  (if (string=? side "asset")
      (append (filter (lambda (account)
                        (or (stays-on-its-types-side? account)
                            (>= (balance account) 0)))
                      asset-accounts)
              (filter (lambda (account)
                        (and (not (stays-on-its-types-side? account))
                             (> (balance account) 0)))
                      liability-accounts))
      (append (filter (lambda (account)
                        (or (stays-on-its-types-side? account)
                            (<= (balance account) 0)))
                      liability-accounts)
              (filter (lambda (account)
                        (and (not (stays-on-its-types-side? account))
                             (< (balance account) 0)))
                      asset-accounts))))

(define (plaintext:held-in accounts commodity moment)
  (let loop ((rest accounts) (total 0))
    (if (null? rest)
        total
        (loop (cdr rest)
              (if (gnc-commodity-equiv (xaccAccountGetCommodity (car rest)) commodity)
                  (+ total (plaintext:exact
                            (xaccAccountGetBalanceAsOfDate (car rest) moment)))
                  total)))))

;; A cost basis as gnucash-plaintext hands it over: the currency's mnemonic,
;; the balance still against it, what that balance cost, and which side of the
;; sheet it sits on — "asset" for currency the book holds, "liability" for
;; currency it owes. The owed side's figures are negative, so the two sides add
;; to what the currency comes to altogether.
(define (plaintext:basis-mnemonic basis) (car basis))
(define (plaintext:basis-balance basis) (car (cdr basis)))
(define (plaintext:basis-cost basis) (car (cdr (cdr basis))))
(define (plaintext:basis-side basis) (car (cdr (cdr (cdr basis)))))
(define (plaintext:basis-namespace basis) (car (cdr (cdr (cdr (cdr basis))))))
(define (plaintext:basis-cost-held basis) (list-ref basis 5))

;; What this commodity's cost bases on this side say the holding cost, in the
;; report's currency — or #f where the book keeps none for it.
;;
;; Each cost basis is summed at the report's own places before they are added,
;; as `plaintext:revaluation` sums them, so the figure the items print is the
;; figure the key is measured from and a reader adding the items up reaches it.
(define (plaintext:cost-from-bases commodity side report-commodity)
  (let ((mnemonic (gnc-commodity-get-mnemonic commodity)))
    (let loop ((rest (plaintext:cost-bases)) (spent 0) (found #f))
      (if (null? rest)
          (and found spent)
          (let ((basis (car rest)))
            (if (and (string=? (plaintext:basis-mnemonic basis) mnemonic)
                     (string=? (plaintext:basis-side basis) side))
                (loop (cdr rest)
                      (+ spent (plaintext:as-money (plaintext:basis-cost basis)
                                                   report-commodity))
                      #t)
                (loop (cdr rest) spent found)))))))

;; The commodity a cost basis of this mnemonic and side is in, or #f.
;;
;; Looked up under the namespace the cost basis itself carries, which is the
;; only way a share is found: `gnc-commodity-table-lookup` takes a namespace
;; and a mnemonic, and a page asking for `USD_CORP` under `CURRENCY` is told
;; there is no such commodity and leaves every security to GnuCash.
(define (plaintext:commodity-of table mnemonic side)
  (let loop ((rest (plaintext:cost-bases)))
    (cond ((null? rest) #f)
          ((and (string=? (plaintext:basis-mnemonic (car rest)) mnemonic)
                (string=? (plaintext:basis-side (car rest)) side))
           (gnc-commodity-table-lookup table
                                       (plaintext:basis-namespace (car rest))
                                       mnemonic))
          (else (loop (cdr rest))))))

;; Whether this cost basis balance is what the book still has on that side.
;;
;; The two are one figure where every disposal said which cost basis it came
;; out of: a cost basis balance is what came in, less what each disposal drew
;; down. Where they differ, currency was spent without saying, and what is left
;; of the balance stands for money the book no longer has — pricing it would
;; state a gain on dollars that are gone.
;;
;; `accounts` is one side's, never both. A book holding a currency and owing it
;; at once would otherwise match on neither: a loan's balance checked against a
;; bank's as well answers for a figure neither of them has.
;;
;; Measured on the book of Q-042's tests: a USD cost basis balance of 10,000.00
;; against 7,480.00 in the bank, and an HKD one of 5,500.00 against 5,500.00.
;; Asked of one basis, answered for its whole currency and side. Each basis is
;; its own record now, so its balance is a share of what that side holds and
;; never equals it: three arrivals of 1,000.00, 2,000.00 and 1,000.00 USD are
;; each checked against the 4,000.00 in the bank, all three miss, and the
;; currency falls back to GnuCash's revaluation with the cost bases silently
;; dropped. What the check is for is whether a side's bases account for what it
;; holds, which is a question about the group, so the group is what is summed.
(define (plaintext:basis-matches-holdings? basis accounts moment table)
  ;; Looked up under the namespace the cost basis carries, not under
  ;; `CURRENCY`: a share's commodity lives in its exchange's namespace, so
  ;; `USCO` under `CURRENCY` finds nothing and every security is left to
  ;; GnuCash's revaluation however well its cost bases account for it.
  (let ((commodity (gnc-commodity-table-lookup
                    table
                    (plaintext:basis-namespace basis)
                    (plaintext:basis-mnemonic basis))))
    (and commodity
         (= (plaintext:held-in accounts commodity moment)
            (let loop ((rest (plaintext:cost-bases)) (total 0))
              (if (null? rest)
                  total
                  (loop (cdr rest)
                        (if (and (string=? (plaintext:basis-mnemonic (car rest))
                                           (plaintext:basis-mnemonic basis))
                                 (string=? (plaintext:basis-side (car rest))
                                           (plaintext:basis-side basis)))
                            (+ total (plaintext:basis-balance (car rest)))
                            total))))))))

;; True when this commodity's gain on this side is the book's own to measure: a
;; currency its cost bases speak for, whose balance matches what that side
;; holds. Everything else keeps GnuCash's own revaluation.
;;
;; Plain recursion rather than `any` and `fold`: those are SRFI-1, and the
;; module this report is loaded into does not bind them — every page died with
;; an unbound variable, the same way `gnc-commodity-is-currency?` did.
(define (plaintext:measured-from-cost-bases? commodity side accounts moment)
  (and commodity
       ;; Holding no price is no reason to leave the currency to GnuCash.
       ;; `price-fn` answers #f on 3.4 and 3.8 where the book has no price, and
       ;; 0 from 4.4 on, and 0 is true in Scheme — so a guard on the price alone
       ;; had the two halves of the supported range draw different pages.
       ;;
       ;; Which way that fell depended on how the currency arrived, and the two
       ;; cases pull against each other. Bought with the book's own money, its
       ;; account's split values are in the book's currency, GnuCash's
       ;; revaluation is right, and falling back to it costs nothing: 1,000.00
       ;; HKD bought for 180.00 CAD states -180.00 and balances either way.
       ;; Arrived in its own currency — a US dollar invoice collected into a US
       ;; dollar bank — no split carries a figure in the book's currency at all,
       ;; so GnuCash's revaluation is 0, and falling back to it drops the whole
       ;; cost. Measured on 3.8: that book stated 0.00 of assets against
       ;; 3,791.14 of liabilities and equity, while 5.10 kept the cost basis and
       ;; balanced.
       ;;
       ;; So a missing price is read as a price of nothing — here, in
       ;; `plaintext:revaluation` and in `plaintext:cost-basis-block` — and
       ;; every build draws the page 4.4 and later already drew.
       ;;
       ;; The first row of this currency and side answers for the whole group,
       ;; and the loop stops there whichever way it answers.
       ;; `plaintext:basis-matches-holdings?` sums every row of the group before
       ;; comparing, so it returns the same answer for each of them; carrying on
       ;; to the next row after a #f asked the identical question again, and
       ;; each asking walks every account on the side with
       ;; `xaccAccountGetBalanceAsOfDate` and rebuilds the whole
       ;; `(plaintext:cost-bases)` list. On a group that does not match — which
       ;; is a currency spent without stating its basis's guid, the ordinary case
       ;; this fallback exists for — that was the work repeated once per basis,
       ;; with this procedure itself called once per foreign account and once
       ;; per currency and side above.
       (let ((table (gnc-commodity-table-get-table (gnc-get-current-book)))
             (mnemonic (gnc-commodity-get-mnemonic commodity)))
         (let loop ((bases (plaintext:cost-bases)))
           (cond ((null? bases) #f)
                 ((and (string=? (plaintext:basis-mnemonic (car bases)) mnemonic)
                       (string=? (plaintext:basis-side (car bases)) side))
                  (plaintext:basis-matches-holdings?
                   (car bases) accounts moment table))
                 (else (loop (cdr bases))))))))

;; The foreign-currency accounts of one side whose commodity the cost bases
;; cannot speak for, and which therefore keep GnuCash's own revaluation.
;;
;; One definition, asked by both the figure and the working that explains it: a
;; second copy of this filter could come to disagree with the first, and a
;; working that disagreed with its own key is worse than no working at all.
(define (plaintext:fallback-accounts side accounts moment report-commodity)
  (filter (lambda (account)
            (let ((commodity (xaccAccountGetCommodity account)))
              (and (plaintext:foreign-currency? commodity report-commodity)
                   (not (plaintext:measured-from-cost-bases?
                         commodity side accounts moment)))))
          accounts))

;; The accounts holding something that is not a currency — a stock, a mutual
;; fund. Counted in units and priced rather than converted, so they open no
;; cost basis however their accounts are typed.
(define (plaintext:securities accounts)
  (filter (lambda (account)
            (let ((commodity (xaccAccountGetCommodity account)))
              (and commodity
                   (not (string=? (gnc-commodity-get-namespace commodity)
                                  "CURRENCY")))))
          accounts))

;; Those of the security accounts whose cost bases cannot speak for what the
;; accounts hold, and which therefore keep GnuCash's own revaluation. A share
;; bought before this book kept cost bases for shares is the ordinary case, and
;; so is one bought in a transaction stating no figure in the book's currency
;; and never handed a cost by the currency it spent.
(define (plaintext:securities-gnucash-keeps accounts moment)
  (filter (lambda (account)
            (not (plaintext:measured-from-cost-bases?
                  (xaccAccountGetCommodity account) "asset" accounts moment)))
          accounts))

;; `unrealized_gains_assets_fx` with its cost bases under it, grouped by
;; commodity and type and never added before the page is written: each basis
;; states the balance it holds, what that cost, what it is worth at the sheet's
;; price and the difference; the commodity adds its bases up; the key adds the
;; commodities. Q-044 fixes the shape.
;; The accounts of one side holding this commodity, each with what it holds.
;;
;; Printed beside the cost bases because those are the two figures the report
;; chooses between: what the bases say is still against this currency, and what
;; the book's own accounts hold of it. They are one figure where every disposal
;; stated the cost basis it drew on. Where they differ, currency left without
;; saying which basis it came out of, and a reader could previously only find
;; that out by adding up another key's split list.
;; The accounts of `accounts` that are held in `commodity`, in order. Separate
;; from the rendering because the `accounts:` line above states how many there
;; are before any of them is drawn, and counting the unfiltered list would
;; announce a number that includes every account in another commodity.
(define (plaintext:accounts-in accounts commodity)
  (let keep ((rest accounts) (found '()))
    (cond ((null? rest) (reverse found))
          ((and commodity
                (gnc-commodity-equiv (xaccAccountGetCommodity (car rest))
                                     commodity))
           (keep (cdr rest) (cons (car rest) found)))
          (else (keep (cdr rest) found)))))

(define (plaintext:commodity-accounts accounts commodity moment)
  (let* ((mine (plaintext:accounts-in accounts commodity))
         (missing (plaintext:left-out (length mine))))
   (let loop ((rest (plaintext:first-of mine)) (lines '()))
    (if (null? rest)
        ;; With the balance the accounts left out hold between them, because
        ;; `balance_value` on the line beneath says it is the sum of these and
        ;; a reader adding them up has to reach it. These are all one
        ;; commodity, so unlike a security's split lines they do add: a cap of
        ;; one on a currency spread over a receivable and a bank listed the
        ;; receivable's 0.00, said one was left out, and then stated a
        ;; `balance_value` of 1,000.00 that nothing on the page accounted for.
        (append lines
                (if (> missing 0)
                    (plaintext:not-listed
                     5 missing
                     (list (cons "balance"
                                 (plaintext:figure
                                  (let sum ((xs (plaintext:after-first mine)) (n 0))
                                    (if (null? xs)
                                        n
                                        (sum (cdr xs)
                                             (+ n (plaintext:exact
                                                   (xaccAccountGetBalanceAsOfDate
                                                    (car xs) moment))))))
                                  (plaintext:places-of commodity)))))
                    '()))
        (loop (cdr rest)
                  (append
                   lines
                   ;; `account:` carries the path, because that is what an
                   ;; account is called in this format — the same key the cost
                   ;; basis rows above use, and the same colon-joined path
                   ;; every account line on the page writes.
                   ;; `plaintext:full-name` rather than
                   ;; `gnc-account-get-full-name`: the latter joins with the
                   ;; book's own separator, a dot in these images, which would
                   ;; print one account two ways inside a single commodity.
                   ;; `account:` opens an entry and its three facts sit under
                   ;; it, the shape `cost_basis:` uses above. Flat keys could
                   ;; not say which balance belonged to which account —
                   ;; `account:`, `balance:`, `account:`, `balance:` is four
                   ;; keys and no pairing — and a currency spread across
                   ;; several accounts is what this block is for.
                   ;;
                   ;; The guid is guarded the way the balancing block guards
                   ;; `gncSplitGetGUID`: read where the build binds it, and an
                   ;; empty string where it does not, rather than taking the
                   ;; page down over an identifier.
                   (list (string-append (plaintext:indent 5) "account:")
                         (string-append
                          (plaintext:indent 6) "guid: "
                          (let ((found (false-if-exception
                                        (gncAccountGetGUID (car rest)))))
                            (if (string? found) found "")))
                         (string-append
                          (plaintext:indent 6) "name: \""
                          (plaintext:full-name (car rest)) "\"")
                         (string-append
                          (plaintext:indent 6) "balance: "
                          (plaintext:figure
                           (xaccAccountGetBalanceAsOfDate (car rest) moment)
                           (plaintext:places-of commodity))))))))))

;; What the commodities left to GnuCash's revaluation are worth between them,
;; and what they cost, each asked of `revalue` one commodity at a time so that
;; the figures added here are the ones printed above.
(define (plaintext:fallen-back-worth revalue accounts commodities)
  (let sum ((rest commodities) (total 0))
    (if (null? rest)
        total
        (sum (cdr rest)
             (+ total (car (revalue (plaintext:holding accounts (car rest)))))))))

(define (plaintext:fallen-back-cost revalue accounts commodities)
  (let sum ((rest commodities) (total 0))
    (if (null? rest)
        total
        (sum (cdr rest)
             (+ total (cdr (revalue (plaintext:holding accounts (car rest)))))))))

;; One cost basis as the items print it, under whichever key the difference
;; belongs to. Three lines state what a unit cost, because the book-currency
;; figure alone cannot be checked: `cost_share_price` is the price the trade
;; happened at, in the currency the transaction was stated in;
;; `cost_rate` is that currency in the report's on the same day; and
;; `cost_share_price_in_base` is the two multiplied out, which is what every
;; gain is measured against. A currency bought with the book's own money makes
;; the first and the third the same number and the rate 1, which is why a share
;; priced in a foreign currency is the first holding to need them apart (Q-046).
(define (plaintext:basis-entry item bal cv vl commodity report-commodity gain-key)
  ;; The disposals pending their cost basis come as a row of their own,
  ;; `$pending$`, at what their transactions recorded: nothing was bought on a
  ;; day, so its comments say what the figures are instead.
  (let* ((places (plaintext:places-of report-commodity))
         (pending? (string=? (plaintext:basis-item-guid item) "$pending$")))
    (list
     (string-append (plaintext:indent 5) "cost_basis:")
     (string-append (plaintext:indent 6) "split_guid: "
                    (plaintext:basis-item-guid item))
     (string-append (plaintext:indent 6) "account: \""
                    (plaintext:basis-item-account item) "\"")
     (string-append (plaintext:indent 6) "cost_basis_balance: "
                    (plaintext:figure
                     bal (plaintext:places-or report-commodity commodity)))
     (string-append (plaintext:indent 6) "cost_share_price: "
                    (plaintext:figure
                     (plaintext:basis-item-cost-in-pair item) 0)
                    ;; A pending row's cost is only its rate below, so the
                    ;; price in its own commodity says nothing and is not
                    ;; described: "AMZN in AMZN" would be read as a price.
                    (if pending?
                        ""
                        (string-append
                         " # " (plaintext:basis-item-currency item) " in "
                         (plaintext:basis-item-pair-currency item)
                         ", on the day it was bought")))
     (string-append (plaintext:indent 6) "cost_rate: "
                    (plaintext:figure (plaintext:basis-item-cost-rate item) 0)
                    " # " (gnc-commodity-get-mnemonic report-commodity) " per "
                    (plaintext:basis-item-pair-currency item)
                    (if pending?
                        ", what the pending disposals' transactions recorded"
                        ", on that same day"))
     (string-append (plaintext:indent 6) "cost_share_price_in_base: "
                    (plaintext:figure
                     (plaintext:basis-item-cost item) 0)
                    " # cost_share_price * cost_rate")
     (string-append (plaintext:indent 6) "cost_value: "
                    (plaintext:figure cv places)
                    " # cost_basis_balance * cost_share_price_in_base")
     (string-append (plaintext:indent 6) "value: "
                    (plaintext:figure vl places)
                    " # cost_basis_balance * share_price")
     (string-append (plaintext:indent 6) gain-key ": "
                    (plaintext:figure (- vl cv) places)
                    " # value - cost_value"))))

;; The cost bases of one commodity on one side, in the order they were passed.
(define (plaintext:bases-of commodity side)
  (let loop ((rest plaintext:cost-basis-items) (found '()))
    (if (null? rest)
        (reverse found)
        (loop (cdr rest)
              (if (and (string=? (plaintext:basis-item-currency (car rest)) commodity)
                       (string=? (plaintext:basis-item-side (car rest)) side))
                  (cons (car rest) found)
                  found)))))

(define (plaintext:cost-basis-block price-fn report-commodity moment accounts
                                    revalue)
  (let* ((table (gnc-commodity-table-get-table (gnc-get-current-book)))
         ;; The asset side alone. This block is what
         ;; `unrealized_gains_assets_fx` is made of, and what the book owes is
         ;; the separate `unrealized_gains_liabilities_fx` key. Listed here as
         ;; well, a borrowing's cost basis was added into the assets key:
         ;; measured on a CAD book whose only foreign thing is a 1,000.00 USD
         ;; loan drawn at 1.30 and worth 1,400.00 by the report's date, the
         ;; block stated 100.00 of gain under the assets key on a page whose
         ;; `unrealized_gains_fx` says the book has lost 100.00.
         ;; And only the commodities the key is measured from. A currency whose
         ;; cost bases do not account for what the accounts hold keeps
         ;; GnuCash's own revaluation, and `plaintext:revaluation` passes its
         ;; bases over for that reason — so pricing them here at the sheet's
         ;; rate made the block come to something the key never states: 1300.00
         ;; under a key reading 940.00, above a line calling itself the sum of
         ;; that block and the owed side.
         (pairs-of-assets
          (let keep ((rest (plaintext:cost-basis-pairs)) (found '()))
            (cond ((null? rest) (reverse found))
                  ((and (string=? (cdr (car rest)) "asset")
                        (plaintext:measured-from-cost-bases?
                         (gnc-commodity-table-lookup
                          table "CURRENCY" (car (car rest)))
                         "asset" accounts moment))
                   (keep (cdr rest) (cons (car rest) found)))
                  (else (keep (cdr rest) found)))))
         ;; The accounts the key falls back to GnuCash's revaluation for. They
         ;; belong in this block because the key includes them: left out, the
         ;; items came to less than the figure above them.
         (fallback (plaintext:fallback-accounts "asset" accounts moment
                                                report-commodity))
         (fallen-back (plaintext:commodities-of fallback))
         ;; Both kinds of group are entries of the one `commodities:` list, so
         ;; the cap counts them together and the note says how many there are
         ;; altogether. Counting only the cost basis pairs would announce a
         ;; number smaller than the list a reader can see.
         (groups (+ (length pairs-of-assets) (length fallen-back))))
    (let outer ((pairs pairs-of-assets)
                (lines (list (string-append
                              (plaintext:indent 1) "unrealized_gains_assets_fx:")
                             ;; The note stands in place of the list, so it is
                             ;; written only where the list is empty of both
                             ;; kinds of group. A book whose only foreign
                             ;; currency arrived in a transaction stated wholly
                             ;; in that currency has no cost basis for it and
                             ;; still gets a `commodity:` group, measured
                             ;; GnuCash's way — checking the cost basis pairs
                             ;; alone announced "there is no cost basis" and
                             ;; then listed one.
                             (string-append
                              (plaintext:indent 2) "commodities:"
                              (plaintext:listing-note
                               ;; "on the asset side", because the owed side is
                               ;; measured from cost bases of its own and has
                               ;; its own key. The USD-loan book has a cost
                               ;; basis — `unrealized_gains_liabilities_fx`
                               ;; states -100.00 from it — and this block was
                               ;; telling a reader the book had none.
                               groups "commodities" "commodity"
                               " # there is no cost basis on the asset side"))))
                (all-held 0) (all-spent 0) (all-worth 0)
                (drawn 0) (rest-cost 0) (rest-worth 0))
      (if (null? pairs)
          (append
           lines
           ;; Every commodity left to GnuCash's revaluation, one group each,
           ;; stating what GnuCash makes of it. It carries no cost basis lines
           ;; because it has no cost basis the book can stand behind — that is
           ;; the whole reason it is here — so it states the figure and says
           ;; where the figure came from.
           (let each ((rest fallen-back) (out '()) (n drawn)
                      (rc rest-cost) (rw rest-worth))
             (if (null? rest)
                 ;; The entry the `commodities:` note promises, over both kinds
                 ;; of group: the cost and the worth of everything the cap left
                 ;; out, so the groups drawn plus this one still come to the
                 ;; two totals below.
                 (append out
                         (if (> (plaintext:left-out groups) 0)
                             (plaintext:not-listed
                              3 (plaintext:left-out groups)
                              (list (cons "cost_value"
                                          (plaintext:figure
                                           rc (plaintext:places-of report-commodity)))
                                    (cons "value"
                                          (plaintext:figure
                                           rw (plaintext:places-of report-commodity)))
                                    (cons "unrealized_gains_assets_fx"
                                          (plaintext:figure
                                           (- rw rc)
                                           (plaintext:places-of report-commodity)))))
                             '()))
                 (let ((parts (revalue (plaintext:holding fallback (car rest)))))
                   (each
                    (cdr rest)
                    (if (not (plaintext:room-for? n))
                        out
                    (append
                     out
                     (list (string-append (plaintext:indent 3) "commodity:")
                           (string-append
                            (plaintext:indent 4) "commodity.mnemonic: \""
                            (gnc-commodity-get-mnemonic (car rest)) "\"")
                           (string-append (plaintext:indent 4) "type: asset")
                           (string-append
                            (plaintext:indent 4) "measured_from: gnucash_revaluation"
                            (plaintext:why-measured-from-revaluation))
                           (string-append
                            (plaintext:indent 4) "cost_value: "
                            (plaintext:figure (cdr parts)
                                              (plaintext:places-of report-commodity))
                            " # what its splits were recorded at, converted")
                           (string-append
                            (plaintext:indent 4) "value: "
                            (plaintext:figure (car parts)
                                              (plaintext:places-of report-commodity))
                            " # what the accounts hold, at the sheet's price")
                           (string-append
                            (plaintext:indent 4) "unrealized_gains_assets_fx: "
                            (plaintext:figure (- (car parts) (cdr parts))
                                              (plaintext:places-of report-commodity))
                            " # value - cost_value"))))
                    (+ n 1)
                    (if (plaintext:room-for? n) rc (+ rc (cdr parts)))
                    (if (plaintext:room-for? n) rw (+ rw (car parts)))))))
           ;; No `cost_basis_balance` at this depth. Per commodity it is that
           ;; commodity's own units and means something; added across them it
           ;; is US dollars and Hong Kong dollars in one number — 100110.00 on
           ;; the book that showed it — which is a quantity of nothing.
           ;; Every commodity's figures, however it was measured: the ones from
           ;; cost bases and the ones from GnuCash's revaluation are both a
           ;; value and a cost, so both belong in these sums and the equation
           ;; on the last line is the equation it says it is.
           (let ((spent (+ all-spent (plaintext:fallen-back-cost revalue
                                                                 fallback fallen-back)))
                 (worth (+ all-worth (plaintext:fallen-back-worth revalue
                                                                  fallback fallen-back))))
             (list (string-append
                    (plaintext:indent 2) "cost_value: "
                    (plaintext:figure spent (plaintext:places-of report-commodity))
                    " # sum of each commodity's cost_value")
                   (string-append
                    (plaintext:indent 2) "value: "
                    (plaintext:figure worth (plaintext:places-of report-commodity))
                    " # sum of each commodity's value")
                   (string-append
                    (plaintext:indent 2) "unrealized_gains_assets_fx: "
                    (plaintext:figure (- worth spent)
                                      (plaintext:places-of report-commodity))
                    " # value - cost_value"))))
          (let* ((pair (car pairs))
                 (commodity (gnc-commodity-table-lookup
                             table "CURRENCY" (car pair)))
                 (price (plaintext:exact
                         (or (and commodity (price-fn commodity)) 0))))
            (let inner ((rest plaintext:cost-basis-items)
                        (rows '()) (held 0) (spent 0) (seen 0)
                        (rest-bal 0) (rest-cv 0) (rest-vl 0))
              (if (null? rest)
                  (let* ((worth (plaintext:as-money (* held price) report-commodity))
                         (rise (- worth spent)))
                    (outer
                     (cdr pairs)
                     (if (not (plaintext:room-for? drawn))
                         lines
                     (append
                      lines
                      (list (string-append (plaintext:indent 3) "commodity:")
                            (string-append
                             (plaintext:indent 4) "commodity.mnemonic: \""
                             (car pair) "\"")
                            (string-append
                             (plaintext:indent 4) "type: " (cdr pair))
                            (string-append
                             (plaintext:indent 4) "share_price: "
                             (plaintext:figure price 0)
                             " # current price of commodity in balance sheet currency")
                            (string-append
                             (plaintext:indent 4) "cost_bases:"
                             (plaintext:listing-note seen "cost bases"
                                                     "cost basis" "")))
                      rows
                      (if (> (plaintext:left-out seen) 0)
                          (plaintext:not-listed
                           5 (plaintext:left-out seen)
                           (list (cons "cost_basis_balance"
                                       (plaintext:figure
                                        rest-bal
                                        (plaintext:places-or report-commodity
                                                             commodity)))
                                 (cons "cost_value"
                                       (plaintext:figure
                                        rest-cv
                                        (plaintext:places-of report-commodity)))
                                 (cons "value"
                                       (plaintext:figure
                                        rest-vl
                                        (plaintext:places-of report-commodity)))
                                 (cons "unrealized_gains_assets_fx"
                                       (plaintext:figure
                                        (- rest-vl rest-cv)
                                        (plaintext:places-of report-commodity)))))
                          '())
                      (list (string-append
                             (plaintext:indent 4) "cost_basis_balance: "
                             (plaintext:figure
                              held (plaintext:places-or report-commodity commodity))
                             " # sum of each cost_basis's cost_basis_balance")
                            (string-append
                             (plaintext:indent 4) "cost_value: "
                             (plaintext:figure
                              spent (plaintext:places-of report-commodity))
                             " # sum of each cost_basis's cost_value")
                            (string-append
                             (plaintext:indent 4) "accounts:"
                             (plaintext:listing-note
                              (length (plaintext:accounts-in accounts commodity))
                              "accounts" "account" "")))
                      (plaintext:commodity-accounts accounts commodity moment)
                      (list (string-append
                             (plaintext:indent 4) "balance_value: "
                             (plaintext:figure
                              (if commodity
                                  (plaintext:held-in accounts commodity moment)
                                  0)
                              (plaintext:places-or report-commodity commodity))
                             " # sum of account's balance for all accounts")
                            (string-append
                             (plaintext:indent 4) "value: "
                             (plaintext:figure
                              worth (plaintext:places-of report-commodity))
                             " # cost_basis_balance * share_price")
                            (string-append
                             (plaintext:indent 4) "unrealized_gains_assets_fx: "
                             (plaintext:figure
                              rise (plaintext:places-of report-commodity))
                             " # value - cost_value"))))
                     (+ all-held held) (+ all-spent spent) (+ all-worth worth)
                     (+ drawn 1)
                     (if (plaintext:room-for? drawn) rest-cost (+ rest-cost spent))
                     (if (plaintext:room-for? drawn) rest-worth (+ rest-worth worth))))
                  (let ((item (car rest)))
                    (if (and (string=? (plaintext:basis-item-currency item)
                                       (car pair))
                             (string=? (plaintext:basis-item-side item)
                                       (cdr pair)))
                        (let* ((bal (plaintext:basis-item-balance item))
                               (cst (plaintext:basis-item-cost item))
                               (cv (plaintext:as-money (* bal cst) report-commodity))
                               (vl (plaintext:as-money (* bal price) report-commodity)))
                          (inner
                           (cdr rest)
                           (if (plaintext:room-for? seen)
                               (append rows
                                       (plaintext:basis-entry
                                        item bal cv vl commodity report-commodity
                                        "unrealized_gains_assets_fx"))
                               rows)
                           (+ held bal) (+ spent cv) (+ seen 1)
                           (if (plaintext:room-for? seen) rest-bal (+ rest-bal bal))
                           (if (plaintext:room-for? seen) rest-cv (+ rest-cv cv))
                           (if (plaintext:room-for? seen) rest-vl (+ rest-vl vl))))
                        (inner (cdr rest) rows held spent seen
                               rest-bal rest-cv rest-vl))))))))))

;; The accounts holding one security, each with its balance and the splits that
;; brought it there.
;;
;; A split is written as one reading — `split_amount 20.0000 | value 4000.00
;; USD` — and not as two `key: value` lines. The two figures are checked
;; against each other, never separately: what the account gained in units
;; beside what that cost in the transaction's currency is how a reader tells a
;; purchase from a revaluation. Splitting them across two lines, or nesting
;; them under a `split:` of their own, puts the pair a reader is comparing
;; further apart for the sake of a shape. That is the author's decision about
;; this line and it is deliberate.
(define (plaintext:security-accounts held moment)
  (let loop ((rest (plaintext:first-of held)) (lines '()))
    (if (null? rest)
        ;; With the balance the accounts left out hold between them. `value:`
        ;; and `cost_value:` beneath are converted rather than summed from
        ;; these, but `quantity:` four lines above is exactly their sum, so a
        ;; count alone left a reader unable to reach it: two accounts holding
        ;; 1.0000 each, capped at one, stated `quantity: 2.0000` over a single
        ;; 1.0000 and a count of one. This is the same figure
        ;; `plaintext:commodity-accounts` carries for a currency, and for the
        ;; same reason.
        (append lines
                (if (> (plaintext:left-out (length held)) 0)
                    (plaintext:not-listed
                     5 (plaintext:left-out (length held))
                     (list (cons "balance"
                                 (plaintext:figure
                                  (let sum ((xs (plaintext:after-first held)) (n 0))
                                    (if (null? xs)
                                        n
                                        (sum (cdr xs)
                                             (+ n (plaintext:exact
                                                   (xaccAccountGetBalanceAsOfDate
                                                    (car xs) moment))))))
                                  (plaintext:places-of
                                   (xaccAccountGetCommodity (car held)))))))
                    '()))
        (let* ((account (car rest))
               ;; The splits of this account on or before the sheet's date, as
               ;; one list, so the cap and the note it writes are counting the
               ;; same thing. Counting `xaccAccountGetSplitList` instead would
               ;; announce a number that includes splits dated after the sheet,
               ;; which the listing does not show and a reader cannot find.
               (dated (let keep ((all (xaccAccountGetSplitList account))
                                 (found '()))
                        (cond ((null? all) (reverse found))
                              ((<= (xaccTransGetDate
                                    (xaccSplitGetParent (car all))) moment)
                               (keep (cdr all) (cons (car all) found)))
                              (else (keep (cdr all) found))))))
          (loop
           (cdr rest)
           (append
            lines
            (list (string-append (plaintext:indent 5) "account:")
                  (string-append
                   (plaintext:indent 6) "guid: "
                   (let ((found (false-if-exception
                                 (gncAccountGetGUID account))))
                     (if (string? found) found "")))
                  (string-append (plaintext:indent 6) "name: \""
                                 (plaintext:full-name account) "\"")
                  (string-append
                   (plaintext:indent 6) "balance: "
                   (plaintext:figure
                    (xaccAccountGetBalanceAsOfDate account moment)
                    (plaintext:places-of (xaccAccountGetCommodity account))))
                  ;; A count and no `not_listed:` entry, unlike the lists that
                  ;; end in a total. These lines are a reading of one split
                  ;; each — units in the security beside what they cost in
                  ;; whatever currency that transaction was stated in — and
                  ;; several transactions' currencies do not add to anything.
                  ;; The figure they stand behind is `cost_value` above, which
                  ;; is converted rather than summed from these.
                  (string-append
                   (plaintext:indent 6) "splits:"
                   (plaintext:listing-note (length dated) "splits" "split"
                                           " # there is no split")))
            (let splits ((rest (plaintext:first-of dated)) (out '()))
              (if (null? rest)
                  out
                  (let ((txn (xaccSplitGetParent (car rest))))
                    (splits
                     (cdr rest)
                     (append
                      out
                      (list (string-append
                             (plaintext:indent 7) "split_amount "
                             (plaintext:figure
                              (xaccSplitGetAmount (car rest))
                              (plaintext:places-of
                               (xaccAccountGetCommodity account)))
                             " | value "
                             (plaintext:figure
                              (xaccSplitGetValue (car rest))
                              (plaintext:places-of
                               (xaccTransGetCurrency txn)))
                             " "
                             (gnc-commodity-get-mnemonic
                              (xaccTransGetCurrency txn)))))))))
            ;; The entry the note above promises, carrying a count and no
            ;; figures. The lines it stands for do not add to anything — see
            ;; the note on `splits:` — so there is no total to complete here,
            ;; and a count is the whole of what a reader can be told. Saying
            ;; "the rest under not_listed" and then writing nothing was the
            ;; fault this closes.
            (if (> (plaintext:left-out (length dated)) 0)
                (plaintext:not-listed 7 (plaintext:left-out (length dated)) '())
                '())))))))

;; `unrealized_gains_other` with every security and fund under it. A fund is a
;; security here: `plaintext:securities` takes every account whose commodity is
;; not a currency, so the two arrive in one list and are told apart only by
;; their namespace.
;; The cost bases behind one security, each with what it holds and what a unit
;; of it cost. `price` is what the report priced the security at, so each entry
;; states its own share of the holding's worth beside its own share of the cost.
;; What the cap leaves out is carried in a `not_listed:` entry, as it is under
;; every other list on the page, so the entries still come to `cost_value:`.
(define (plaintext:security-bases commodity price report-commodity)
  (let* ((bases (plaintext:bases-of (gnc-commodity-get-mnemonic commodity)
                                    "asset"))
         (places (plaintext:places-of report-commodity))
         (at (if price (plaintext:exact price) 0)))
    (let each ((rest bases) (drawn 0) (rows '())
               (rest-bal 0) (rest-cv 0) (rest-vl 0))
      (if (null? rest)
          (append
           rows
           (if (> (plaintext:left-out (length bases)) 0)
               (plaintext:not-listed
                5 (plaintext:left-out (length bases))
                (list (cons "cost_basis_balance"
                            (plaintext:figure
                             rest-bal (plaintext:places-of commodity)))
                      (cons "cost_value" (plaintext:figure rest-cv places))
                      (cons "value" (plaintext:figure rest-vl places))
                      (cons "unrealized_gains_other"
                            (plaintext:figure (- rest-vl rest-cv) places))))
               '()))
          (let* ((item (car rest))
                 (bal (plaintext:basis-item-balance item))
                 (cv (plaintext:as-money
                      (* bal (plaintext:basis-item-cost item)) report-commodity))
                 (vl (plaintext:as-money (* bal at) report-commodity))
                 (room (plaintext:room-for? drawn)))
            (each (cdr rest) (+ drawn 1)
                  (if room
                      (append rows (plaintext:basis-entry
                                    item bal cv vl commodity report-commodity
                                    "unrealized_gains_other"))
                      rows)
                  (if room rest-bal (+ rest-bal bal))
                  (if room rest-cv (+ rest-cv cv))
                  (if room rest-vl (+ rest-vl vl))))))))

(define (plaintext:securities-block accounts price-fn report-commodity moment
                                    exchange-fn)
  (let* ((securities (plaintext:commodities-of accounts))
         (count (length securities))
         (places (plaintext:places-of report-commodity)))
   (let every ((rest securities)
              (lines (list (string-append
                            (plaintext:indent 1)
                            "unrealized_gains_other: # sum of"
                            " unrealized_gains_other of all securities and funds")
                           (string-append
                            (plaintext:indent 2) "securities:"
                            (if (= count 0)
                                " # there is no security or fund"
                                (let ((note (plaintext:listing-note
                                             count "securities" "security" "")))
                                  (if (string=? note "")
                                      " # security, fund, etc"
                                      note))))))
              (all-worth 0) (all-recorded 0) (seen 0)
              (rest-worth 0) (rest-recorded 0))
    (if (null? rest)
        (append
         lines
         ;; What the cap left out, so the three totals below still have the
         ;; entries above them adding up to what they say they are.
         (if (> (plaintext:left-out count) 0)
             (plaintext:not-listed
              3 (plaintext:left-out count)
              (list (cons "value" (plaintext:figure rest-worth places))
                    (cons "cost_value" (plaintext:figure rest-recorded places))
                    (cons "unrealized_gains_other"
                          (plaintext:figure (- rest-worth rest-recorded) places))))
             '())
         (list (string-append
                (plaintext:indent 2) "value: "
                (plaintext:figure all-worth (plaintext:places-of report-commodity))
                " # sum of each security's value")
               (string-append
                (plaintext:indent 2) "cost_value: "
                (plaintext:figure all-recorded (plaintext:places-of report-commodity))
                " # sum of each security's cost_value")
               (string-append
                (plaintext:indent 2) "unrealized_gains_other: "
                (plaintext:figure (- all-worth all-recorded)
                                  (plaintext:places-of report-commodity))
                " # value - cost_value")))
        (let* ((commodity (car rest))
               (held (plaintext:holding accounts commodity))
               (price (price-fn commodity))
               (worth (plaintext:converted
                       (plaintext:balance-as-of held moment)
                       report-commodity exchange-fn))
               ;; A cost should not be revalued, so it comes from this
               ;; security's cost bases wherever they account for what the
               ;; accounts hold. The splits' recorded values are used only
               ;; where they do not, and `unrealized_gains_other` is reached
               ;; the same way.
               (measured (plaintext:measured-from-cost-bases?
                          commodity "asset" accounts moment))
               (recorded (or (and measured
                                  (plaintext:cost-from-bases
                                   commodity "asset" report-commodity))
                             (plaintext:converted
                              (gnc:accounts-get-comm-total-assets
                               held
                               (lambda (a)
                                 (gnc:account-get-comm-value-at-date a moment #f)))
                              report-commodity exchange-fn))))
          (every
           (cdr rest)
           (if (plaintext:room-for? seen)
               (append
                lines
                (list (string-append (plaintext:indent 3) "security:")
                      (string-append
                       (plaintext:indent 4) "commodity.namespace: \""
                       (gnc-commodity-get-namespace commodity) "\"")
                      (string-append
                       (plaintext:indent 4) "commodity.mnemonic: \""
                       (gnc-commodity-get-mnemonic commodity) "\"")
                      (string-append
                       (plaintext:indent 4) "quantity: "
                       (plaintext:figure (plaintext:quantity-of held moment)
                                         (plaintext:places-of commodity)))
                      (string-append
                       (plaintext:indent 4) "share_price: "
                       (if price (plaintext:figure (plaintext:exact price) 0) "0")
                       " # what price-fn returns for this commodity"))
                (if measured
                    ;; Where the cost comes from this security's own cost
                    ;; bases, each of them is listed, so `cost_value` below can
                    ;; be followed down to the trades it is made of and the
                    ;; rate each was converted at. Where it does not, there is
                    ;; nothing to list and the line above says so instead.
                    (append
                     (list (string-append
                            (plaintext:indent 4) "cost_bases:"
                            (plaintext:listing-note
                             (length (plaintext:bases-of
                                      (gnc-commodity-get-mnemonic commodity)
                                      "asset"))
                             "cost bases" "cost basis" "")))
                     (plaintext:security-bases commodity price report-commodity))
                    (list (string-append
                           (plaintext:indent 4)
                           "measured_from: gnucash_revaluation"
                           (plaintext:why-measured-from-revaluation))))
                (list (string-append
                       (plaintext:indent 4) "accounts:"
                       (plaintext:listing-note (length held) "accounts"
                                               "account" "")))
                (plaintext:security-accounts held moment)
                (list (string-append
                       (plaintext:indent 4) "value: "
                       (plaintext:figure worth (plaintext:places-of report-commodity))
                       " # the holding converted at the sheet's price")
                      (string-append
                       (plaintext:indent 4) "cost_value: "
                       (plaintext:figure recorded (plaintext:places-of report-commodity))
                       (if measured
                           " # what its cost bases say the units cost"
                           " # its splits' values, converted"))
                      (string-append
                       (plaintext:indent 4) "unrealized_gains_other: "
                       (plaintext:figure (- worth recorded)
                                         (plaintext:places-of report-commodity))
                       " # value - cost_value")))
               lines)
           (+ all-worth worth) (+ all-recorded recorded) (+ seen 1)
           (if (plaintext:room-for? seen) rest-worth (+ rest-worth worth))
           (if (plaintext:room-for? seen)
               rest-recorded
               (+ rest-recorded recorded))))))))

;; How many splits of `accounts` are valued in `currency` at `moment` — what
;; the list under `splits:` would hold, counted before the list is built so
;; that line can say how many there are when the cap shortens it.
(define (plaintext:splits-valued-in accounts currency moment)
  (let loop ((xs accounts) (n 0))
    (if (null? xs)
        n
        (loop (cdr xs)
              (let each ((sp (xaccAccountGetSplitList (car xs))) (m n))
                (if (null? sp)
                    m
                    (let ((txn (xaccSplitGetParent (car sp))))
                      (each (cdr sp)
                            (if (and (<= (xaccTransGetDate txn) moment)
                                     (gnc-commodity-equiv
                                      (xaccTransGetCurrency txn) currency))
                                (+ m 1)
                                m)))))))))

;; What the splits the cap left out come to, walked in the order they are
;; listed in so that the same ones are skipped here as there.
(define (plaintext:splits-left-out accounts currency moment)
  (let loop ((xs accounts) (n 0) (total 0))
    (if (null? xs)
        total
        (let each ((sp (xaccAccountGetSplitList (car xs))) (m n) (acc total))
          (if (null? sp)
              (loop (cdr xs) m acc)
              (let ((txn (xaccSplitGetParent (car sp))))
                (if (and (<= (xaccTransGetDate txn) moment)
                         (gnc-commodity-equiv
                          (xaccTransGetCurrency txn) currency))
                    (each (cdr sp) (+ m 1)
                          (if (plaintext:room-for? m)
                              acc
                              (+ acc (plaintext:exact
                                      (xaccSplitGetValue (car sp))))))
                    (each (cdr sp) m acc))))))))

;; `gnucash_balancing_amount` with what GnuCash subtracted under it, grouped by
;; the currency each split's value is in. Per currency: the splits valued in it,
;; their sum, the accounts holding it and what they hold, the difference between
;; the two, and that difference converted. The key adds the conversions up.
;; The commodities GnuCash's balancing amount is made of, in the order its own
;; collector holds them. Read from the collector rather than worked out from
;; the accounts, so that the items under the key are the terms of GnuCash's own
;; sum and come to it.
(define (plaintext:balancing-commodities gains)
  (map car (gains 'format cons #f)))

(define (plaintext:balancing-block accounts moment report-commodity exchange-fn
                                   price-fn gains)
  (let* ((every-commodity (plaintext:balancing-commodities gains))
         (missing (plaintext:left-out (length every-commodity))))
   ;; The loop runs over every commodity whatever the cap, and the cap decides
   ;; only which of them draw lines. The key beneath is the sum over all of
   ;; them — GnuCash's own figure does not shrink because a reader asked for a
   ;; shorter page — so what the cap leaves out is accumulated into
   ;; `rest-value` and carried in `not_listed:`, and the groups above it plus
   ;; that entry still come to the key.
   ;;
   ;; This list grows with the book like the others: GnuCash's collector holds
   ;; one entry per account commodity, so every stock and fund a brokerage
   ;; holds is a group here, about eleven lines even with its own split and
   ;; account lists capped.
   (let outer ((rest every-commodity)
              (lines (list (string-append
                            (plaintext:indent 1)
                            "gnucash_balancing_amount: # the commodities"
                            " GnuCash's own figure is summed from")
                           (string-append
                            (plaintext:indent 2) "commodities:"
                            (plaintext:listing-note (length every-commodity)
                                                    "commodities" "commodity"
                                                    " # there is no commodity"))))
              (total 0) (seen 0) (rest-value 0))
    (if (null? rest)
        (append lines
                (if (> missing 0)
                    (plaintext:not-listed
                     3 missing
                     (list (cons "balance_sheet_value"
                                 (plaintext:figure
                                  rest-value
                                  (plaintext:places-of report-commodity)))))
                    '())
                (list (string-append
                       (plaintext:indent 2) "gnucash_balancing_amount: "
                       (plaintext:figure total (plaintext:places-of report-commodity))
                       " # sum of balance_sheet_value of all commodities")))
        (let* ((currency (car rest))
               (price (price-fn currency))
               (sum (let s ((xs accounts) (n 0))
                      (if (null? xs)
                          n
                          (s (cdr xs)
                             (let t ((sp (xaccAccountGetSplitList (car xs))) (m n))
                               (if (null? sp)
                                   m
                                   (let ((txn (xaccSplitGetParent (car sp))))
                                     (t (cdr sp)
                                        (if (and (<= (xaccTransGetDate txn) moment)
                                                 (gnc-commodity-equiv
                                                  (xaccTransGetCurrency txn) currency))
                                            (+ m (plaintext:exact
                                                  (xaccSplitGetValue (car sp))))
                                            m)))))))))
               (worth (let w ((xs accounts) (n 0))
                        (if (null? xs)
                            n
                            (w (cdr xs)
                               (if (gnc-commodity-equiv
                                    (xaccAccountGetCommodity (car xs)) currency)
                                   (+ n (plaintext:exact
                                         (xaccAccountGetBalanceAsOfDate
                                          (car xs) moment)))
                                   n)))))
               ;; GnuCash's own amount for this commodity, out of the collector
               ;; it sums, never `worth - sum` worked out here. The two lines
               ;; above are what went into it — the balances it merged and the
               ;; split values it subtracted — and are printed so a reader can
               ;; see where it came from; this is the figure itself.
               (gain (plaintext:exact
                      (gnc:gnc-monetary-amount (gains 'getmonetary currency #f))))
               (converted (plaintext:exact
                           (gnc:gnc-monetary-amount
                            (exchange-fn (gnc:make-gnc-monetary
                                          currency
                                          (gnc-numeric-create (numerator gain)
                                                              (denominator gain)))
                                         report-commodity)))))
          (outer
           (cdr rest)
           (if (not (plaintext:room-for? seen))
               lines
           (append
            lines
            (list (string-append (plaintext:indent 3) "commodity:")
                  (string-append (plaintext:indent 4) "commodity.mnemonic: \""
                                 (gnc-commodity-get-mnemonic currency) "\"")
                  (string-append
                   (plaintext:indent 4) "splits:"
                   (plaintext:listing-note
                    (plaintext:splits-valued-in accounts currency moment)
                    "splits" "split" " # there is no split")))
            (let rows ((xs accounts) (out '()) (shown 0))
              (if (null? xs)
                  out
                  (let each ((sp (xaccAccountGetSplitList (car xs)))
                             (o out) (n shown))
                    (if (null? sp)
                        (rows (cdr xs) o n)
                        (let ((txn (xaccSplitGetParent (car sp))))
                          (if (and (<= (xaccTransGetDate txn) moment)
                                   (gnc-commodity-equiv
                                    (xaccTransGetCurrency txn) currency))
                              (each
                               (cdr sp)
                               (if (plaintext:room-for? n)
                                   (append
                                    o
                                    (list
                                     (string-append (plaintext:indent 5) "split:")
                                     (string-append
                                      (plaintext:indent 6) "split_guid: "
                                      (let ((g (false-if-exception
                                                (gncSplitGetGUID (car sp)))))
                                        (if (string? g) g "")))
                                     (string-append
                                      (plaintext:indent 6) "account: \""
                                      (plaintext:full-name (car xs)) "\"")
                                     (string-append
                                      (plaintext:indent 6) "value: "
                                      (plaintext:figure
                                       (xaccSplitGetValue (car sp))
                                       (plaintext:places-of currency)))))
                                   o)
                               (+ n 1))
                              (each (cdr sp) o n)))))))
            (let ((left-out (plaintext:left-out
                             (plaintext:splits-valued-in accounts currency moment))))
              (if (> left-out 0)
                  (plaintext:not-listed
                   5 left-out
                   (list (cons "value"
                               (plaintext:figure
                                (plaintext:splits-left-out accounts currency moment)
                                (plaintext:places-of currency)))))
                  '()))
            (list (string-append
                   (plaintext:indent 4) "sum_value: "
                   (plaintext:figure sum (plaintext:places-of currency))
                   " # sum of split's value of all splits")
                  ;; The same listing the cost basis block writes, from the same
                  ;; procedure: an account held in this commodity, its guid, its
                  ;; path and its balance, capped the same way and saying so on
                  ;; this line. Written out a second time here, the two drifted
                  ;; — this one was never capped at all — and there is one
                  ;; question being answered, which accounts hold this
                  ;; commodity.
                  (string-append
                   (plaintext:indent 4) "accounts:"
                   (plaintext:listing-note
                    (length (plaintext:accounts-in accounts currency))
                    "accounts" "account" "")))
            (plaintext:commodity-accounts accounts currency moment)
            (list (string-append
                   (plaintext:indent 4) "balance_value: "
                   (plaintext:figure worth (plaintext:places-of currency))
                   " # sum of account's balance for all accounts")
                  (string-append
                   (plaintext:indent 4) "gains_before_conversion: "
                   (plaintext:figure gain (plaintext:places-of currency))
                   " # what GnuCash's own figure holds for this commodity")
                  (string-append
                   (plaintext:indent 4) "balance_sheet_value: "
                   (plaintext:figure converted (plaintext:places-of report-commodity))
                   " # " (plaintext:figure gain (plaintext:places-of currency))
                   " " (gnc-commodity-get-mnemonic currency)
                   " at "
                   ;; No price is a rate of nothing, not a rate of one, and the
                   ;; converted figure beside this comment is already 0 — a
                   ;; missing price is read as a price of nothing everywhere on
                   ;; this page. Stating 1 made the comment contradict the
                   ;; figure it explains: `0.00 # 5.00 USD at 1 CAD per USD`.
                   ;; It showed only on 3.4 and 3.8, where `price-fn` answers #f
                   ;; for a commodity the book prices nowhere, while 4.4 and
                   ;; later answer a price of 0 and printed "at 0" all along.
                   ;; `plaintext:securities-block` says 0 in the same case.
                   (if price (plaintext:figure (plaintext:exact price) 0) "0")
                   " " (gnc-commodity-get-mnemonic report-commodity)
                   " per " (gnc-commodity-get-mnemonic currency)))))
           (+ total converted) (+ seen 1)
           (if (plaintext:room-for? seen) rest-value (+ rest-value converted))))))))

;; The distinct commodities a list of accounts holds, in the order they first
;; appear. Hand-rolled for the reason `plaintext:held-in` is: `delete-duplicates`
;; is SRFI-1, which the module this report is loaded into does not bind.
(define (plaintext:commodities-of accounts)
  (let loop ((rest accounts) (found '()))
    (if (null? rest)
        (reverse found)
        (let ((commodity (xaccAccountGetCommodity (car rest))))
          (loop (cdr rest)
                (if (or (not commodity)
                        (let seen ((rest found))
                          (cond ((null? rest) #f)
                                ((gnc-commodity-equiv (car rest) commodity) #t)
                                (else (seen (cdr rest))))))
                    found
                    (cons commodity found)))))))

;; Those of `accounts` that hold `commodity`.
(define (plaintext:holding accounts commodity)
  (let loop ((rest accounts) (held '()))
    (if (null? rest)
        (reverse held)
        (loop (cdr rest)
              (if (gnc-commodity-equiv (xaccAccountGetCommodity (car rest))
                                       commodity)
                  (cons (car rest) held)
                  held)))))

;; How much of a commodity a list of accounts holds, in that commodity's own
;; units. `plaintext:balance-as-of` answers the same question as a collector,
;; for converting; this answers it as a number, for printing beside the
;; conversion.
(define (plaintext:quantity-of accounts moment)
  (let loop ((rest accounts) (total 0))
    (if (null? rest)
        total
        (loop (cdr rest)
              (+ total (plaintext:exact
                        (xaccAccountGetBalanceAsOfDate (car rest) moment)))))))

;; What the book's foreign currency has gained or lost against what it cost,
;; read from the cost bases alone: each one's remaining balance valued at the
;; report's own closing rate, less what that balance cost. The account holding
;; the money says nothing here — a balance is money, and only a cost basis
;; knows what it was bought for.
;; `want` is `"CURRENCY"` for the two `_fx` keys and the security's own
;; namespace question for `unrealized_gains_other`, passed as the symbol
;; `'security`. The two keys say different things and a commodity belongs to
;; one of them, so each asks for its own and neither counts the other's.
(define (plaintext:revaluation price-fn side accounts moment report-commodity
                               want)
  (let ((table (gnc-commodity-table-get-table (gnc-get-current-book))))
    ;; **A commodity at a time, its whole holding through the price once.**
    ;;
    ;; That is how GnuCash converts, and `total_assets` is that conversion, so
    ;; a gain reached any other way leaves the sheet out of balance. Measured
    ;; on `tests/fixtures/a_cad_book_with_two_cost_bases_that_round_apart.txt`,
    ;; which holds 1.00 USD bought twice and prices the dollar at 1.3833: each
    ;; basis on its own is 1.3833, which is 1.38 at the cent, so two came to
    ;; 2.76 — where the 2.00 USD converts once to 2.7666, which is 2.77 and is
    ;; what the account line and `total_assets` carry. The page stated 100.17
    ;; of assets against 100.16 of liabilities and equity.
    ;;
    ;; The cost is still summed one basis at a time, because that is what each
    ;; basis cost and no conversion is involved: the figures come from the book
    ;; already in this currency.
    (let per ((pairs (plaintext:cost-basis-pairs)) (total 0))
      (if (null? pairs)
          total
          (let* ((pair (car pairs))
                 (commodity (plaintext:commodity-of table (car pair) (cdr pair)))
                 (is-currency (and commodity
                                   (string=? (gnc-commodity-get-namespace commodity)
                                             "CURRENCY")))
                 ;; A price of nothing where the book holds none, as in the
                 ;; working that explains this key — the two must agree, and
                 ;; both must agree across the builds.
                 (price (and commodity (or (price-fn commodity) 0))))
            (per (cdr pairs)
                 (if (and price
                          (if (eq? want 'security) (not is-currency) is-currency)
                          (string=? (cdr pair) side)
                          (plaintext:measured-from-cost-bases?
                           commodity side accounts moment))
                     (+ total
                        (let sum ((rest (plaintext:cost-bases)) (held 0) (spent 0))
                          (if (null? rest)
                              (- (plaintext:as-money (* held (plaintext:exact price))
                                                     report-commodity)
                                 spent)
                              (let ((basis (car rest)))
                                (if (and (string=? (plaintext:basis-mnemonic basis)
                                                   (car pair))
                                         (string=? (plaintext:basis-side basis)
                                                   (cdr pair)))
                                    (sum (cdr rest)
                                         (+ held (plaintext:basis-balance basis))
                                         (+ spent (plaintext:as-money
                                                   (plaintext:basis-cost basis)
                                                   report-commodity)))
                                    (sum (cdr rest) held spent))))))
                     total)))))))

;; The realized gain the book did not record, over the cost bases the
;; unrealized key of `want` and `side` is measured from.
;;
;; A disposal is valued at what it drew cost, rounded to the cent, and its
;; residual split states the gain or loss on it. Several such values add up to
;; more or less than what the currency they drew cost, and the residual splits
;; beside them then add up to that much less or more than the realized gain:
;; 2,720.00 USD that cost 3,815.89 CAD, spent at 1.01, 12.06 and 3,802.81, left
;; 3,815.88, and the book records a realized loss of 44.60 where it is 44.61.
;;
;; Per cost basis it is what the currency still held cost — balance times cost,
;; rounded as `plaintext:revaluation` rounds it — less what the book still
;; holds of the cost, which is what it cost less what its disposals were valued
;; at. The unrealized key measures from the first, and `retained_earnings`
;; carries what the book recorded, so this is what equity needs for the page to
;; balance, and it is a figure of its own rather than a part of either.
;;
;; Each cost basis that has one, as `(item cost-value cost-held difference)`
;; with the owed side's figures negative, so the itemized page lists what the
;; key is the sum of.
(define (plaintext:realized-not-recorded side accounts moment report-commodity want)
  (let ((table (gnc-commodity-table-get-table (gnc-get-current-book))))
    (let per ((pairs (plaintext:cost-basis-pairs)) (found '()))
      (if (null? pairs)
          found
          (let* ((pair (car pairs))
                 (commodity (plaintext:commodity-of table (car pair) (cdr pair)))
                 (is-currency (and commodity
                                   (string=? (gnc-commodity-get-namespace commodity)
                                             "CURRENCY"))))
            (per (cdr pairs)
                 (if (and commodity
                          (if (eq? want 'security) (not is-currency) is-currency)
                          (string=? (cdr pair) side)
                          (plaintext:measured-from-cost-bases?
                           commodity side accounts moment))
                     (let each ((rest plaintext:cost-basis-items) (found found))
                       (if (null? rest)
                           found
                           (let* ((item (car rest))
                                  (sign (if (string=? (plaintext:basis-item-side item)
                                                      "asset")
                                            1 -1))
                                  (cost-value (plaintext:as-money
                                               (* sign (plaintext:basis-item-balance item)
                                                  (plaintext:basis-item-cost item))
                                               report-commodity))
                                  ;; At the cent, as the cost value is: where no
                                  ;; gain is stated the cost held is the cost of
                                  ;; what is still held, and the two then agree.
                                  (cost-held (plaintext:as-money
                                              (* sign (plaintext:basis-item-cost-held item))
                                              report-commodity))
                                  (difference (- cost-value cost-held)))
                             (each (cdr rest)
                                   (if (and (string=? (plaintext:basis-item-currency item)
                                                      (car pair))
                                            (string=? (plaintext:basis-item-side item)
                                                      (cdr pair))
                                            (not (zero? difference)))
                                       (append found
                                               (list (list item cost-value cost-held
                                                           difference)))
                                       found)))))
                     found)))))))

;; `realized_gains_not_recorded` with the cost bases it is made of under it,
;; each with the two figures it is the difference of, in the shape the
;; unrealized keys itemize their cost bases.
(define (plaintext:not-recorded-block entries report-commodity)
  (let ((places (plaintext:places-of report-commodity)))
    (append
     (list (string-append (plaintext:indent 1) "realized_gains_not_recorded:")
           (string-append (plaintext:indent 2) "cost_bases:"
                          (plaintext:listing-note
                           (length entries) "cost bases" "cost basis"
                           " # there is no cost basis")))
     (let loop ((rest (plaintext:first-of entries)) (lines '()))
       (if (null? rest)
           lines
           (let* ((entry (car rest))
                  (item (car entry)))
             (loop (cdr rest)
                   (append
                    lines
                    (list (string-append (plaintext:indent 3) "cost_basis:")
                          (string-append (plaintext:indent 4) "split_guid: "
                                         (plaintext:basis-item-guid item))
                          (string-append (plaintext:indent 4) "account: \""
                                         (plaintext:basis-item-account item) "\"")
                          (string-append (plaintext:indent 4) "cost_basis_balance: "
                                         (plaintext:figure
                                          (plaintext:basis-item-balance item) 0))
                          (string-append (plaintext:indent 4) "cost_share_price_in_base: "
                                         (plaintext:figure
                                          (plaintext:basis-item-cost item) 0))
                          (string-append (plaintext:indent 4) "cost_value: "
                                         (plaintext:figure (car (cdr entry)) places)
                                         " # cost_basis_balance * cost_share_price_in_base")
                          (string-append (plaintext:indent 4) "cost_held: "
                                         (plaintext:figure (car (cdr (cdr entry))) places)
                                         " # what it cost, less what the disposals"
                                         " drawn on it were valued at")
                          (string-append (plaintext:indent 4)
                                         "realized_gains_not_recorded: "
                                         (plaintext:figure
                                          (car (cdr (cdr (cdr entry)))) places)
                                         " # cost_value - cost_held")))))))
     (let ((left-out (plaintext:after-first entries)))
       (if (null? left-out)
           '()
           (plaintext:not-listed
            3 (length left-out)
            (list (cons "realized_gains_not_recorded"
                        (plaintext:figure
                         (let sum ((xs left-out) (total 0))
                           (if (null? xs)
                               total
                               (sum (cdr xs) (+ total (car (cdr (cdr (cdr (car xs)))))))))
                         places))))))
     (list (string-append (plaintext:indent 2) "realized_gains_not_recorded: "
                          (plaintext:figure
                           (let sum ((xs entries) (total 0))
                             (if (null? xs)
                                 total
                                 (sum (cdr xs) (+ total (car (cdr (cdr (cdr (car xs)))))))))
                           places)
                          " # sum of each cost_basis's realized_gains_not_recorded")))))

;; What a collector comes to in the report's currency, as an exact rational.
;; Converted by the report's own exchange function, so every price is GnuCash's
;; and comes from whichever price source the page was asked for.
(define (plaintext:converted collector report-commodity exchange-fn)
  (plaintext:exact
   (gnc:gnc-monetary-amount
    (gnc:sum-collector-commodity collector report-commodity exchange-fn))))

;; True for money the book's cost bases speak for: a currency, and not the one
;; the page is drawn in. A security is counted in units and priced rather than
;; converted, so it establishes no cost basis however its account is typed —
;; `establishes_cost_basis` in services/foreign_currency.py says so — and its
;; cost stays GnuCash's to report.
;; The namespace rather than `gnc-commodity-is-currency?`, which GnuCash's
;; Guile does not bind on any supported build — the report died with an
;; unbound variable on every page. A currency's namespace is "CURRENCY", which
;; is what every block in this format states for one.
(define (plaintext:foreign-currency? commodity report-commodity)
  (and commodity
       (string=? (gnc-commodity-get-namespace commodity) "CURRENCY")
       (not (gnc-commodity-equiv commodity report-commodity))))

;; The prices this commodity has at `moment`, whatever currency they are in.
;; Used only to find a currency to chain through, where the book prices this
;; commodity against no currency the report can reach directly.
(define (plaintext:prices-of commodity moment source)
  (let ((pricedb (gnc-pricedb-get-db (gnc-get-current-book))))
    (if (eq? source 'pricedb-latest)
        (gnc-pricedb-lookup-latest-any-currency pricedb commodity)
        (gnc-pricedb-lookup-nearest-in-time-any-currency-t64
         pricedb commodity (time64CanonicalDayTime moment)))))

;; One price of this exact pair, or #f where the book holds none.
;;
;; The pair is asked for directly rather than filtered out of the "any
;; currency" list. That list is not the same question and does not answer it on
;; every build: on 3.4, with USD priced in CAD at 1.30, 1.35, 1.38 and 1.42,
;; `gnc-pricedb-lookup-latest-any-currency` hands back one USD/CAD price — the
;; 1.38 of 07-15 — and the 1.42 of 12-31 is not in it at all, while
;; `gnc-pricedb-lookup-latest` for USD in CAD answers that 1.42. The page then
;; stated 1.38 beside a value GnuCash had converted at 1.42. Measured on 3.4
;; and 4.13, where the direct lookups agree with each other and with
;; `gnc:case-price-fn`.
;;
;; Either way round, because a book prices a pair whichever way its owner
;; entered it: a CAD book holding `CAD/HKD 5.0` prices a Hong Kong dollar, and
;; the price of the pair is that one inverted. Inverted from the price itself,
;; never by exchanging one unit — GnuCash rounds that unit to the currency's
;; own decimals, so a book pricing CAD in HKD at 5.5 reported HKD at 0.18, a
;; price that multiplies out to 990.00 beside a `value:` of 1000.00. Inverted,
;; it is 2/11, exactly.
(define (plaintext:price-of-pair commodity currency moment source)
  (let ((db (gnc-pricedb-get-db (gnc-get-current-book))))
    (if (eq? source 'pricedb-latest)
        (gnc-pricedb-lookup-latest db commodity currency)
        (gnc-pricedb-lookup-nearest-in-time64
         db commodity currency (time64CanonicalDayTime moment)))))

;; Which way round the price GnuCash handed back runs is read off the price
;; itself, not assumed from the order the pair was asked for. These lookups
;; answer a price of the pair in either direction — asked for HKD in CAD, a
;; book holding `CAD/HKD 5.0` answers that very price — so taking its value as
;; it stood stated 5 where a Hong Kong dollar is 0.2 of a Canadian one, beside a
;; `value:` GnuCash had converted at 0.2.
;; Each price the pricedb hands back is referenced, and `gnc-price-invert`
;; makes another, so both are released once their figure has been read. A
;; report drawing a page for a book of any size looks a price up per line, and
;; a reference kept is a price object held for the life of the process.
(define (plaintext:price-as-quoted price commodity)
  (and price
       (not (null? price))
       (let* ((inverted? (not (gnc-commodity-equiv
                               commodity (gnc-price-get-commodity price))))
              (quoted (if inverted? (gnc-price-invert price) price))
              (value (gnc-price-get-value quoted)))
         (if inverted? (gnc-price-unref quoted))
         (gnc-price-unref price)
         value)))

(define (plaintext:direct-price commodity report-commodity moment source)
  (or (plaintext:price-as-quoted
       (plaintext:price-of-pair commodity report-commodity moment source)
       commodity)
      (plaintext:price-as-quoted
       (plaintext:price-of-pair report-commodity commodity moment source)
       commodity)))

;; The price GnuCash prices this line by, on a build with no `gnc:case-price-fn`.
;;
;; A price of the pair itself where the book holds one. Where it does not, the
;; two prices that reach it: the commodity in some third currency, and that
;; currency in the report's. A book pricing HKD against CAD alone, reported in
;; USD, prices a Hong Kong dollar at 1/5 of a Canadian and a Canadian at 50/71
;; of a US one, so 10/71 — which is what `gnc:case-price-fn` answers from 4.4
;; on, and what 3.4 and 3.8 stated nothing for until they chained it too.
;;
;; Both halves are prices GnuCash returns, and they are multiplied as exact
;; rationals — Scheme's own, not `gnc-numeric-mul`, whose denominator and
;; rounding arguments are bound as procedures rather than integers on 3.4 and
;; 3.8, which are the builds this function runs on: `logior` is handed
;; `#<procedure GNC-HOW-DENOM-REDUCE ()>` and refuses, and the report then
;; renders nothing at all. So the answer states the pair exactly rather than to
;; some number of decimals, and nothing here rounds. It is not a rate worked
;; out from an amount and a value, which is the thing this file must never do.
(define (plaintext:price-of-commodity commodity report-commodity moment source)
  (or (plaintext:direct-price commodity report-commodity moment source)
      (let ((found (plaintext:prices-of commodity moment source)))
        (if (or (not found) (null? found))
            #f
            (let loop ((rest found) (chained #f))
              (if (null? rest)
                  (begin (gnc-price-list-destroy found) chained)
                  (let* ((price (car rest))
                         (holds? (gnc-commodity-equiv
                                  commodity (gnc-price-get-commodity price)))
                         (through (if holds?
                                      (gnc-price-get-currency price)
                                      (gnc-price-get-commodity price)))
                         (leg (and (not chained)
                                   (not (gnc-commodity-equiv through commodity))
                                   (plaintext:direct-price
                                    through report-commodity moment source))))
                    (loop (cdr rest)
                          (or chained
                              (and leg
                                   (* (plaintext:exact
                                       (if holds?
                                           (gnc-price-get-value price)
                                           ;; Inverting makes a price of its
                                           ;; own, released once its figure is
                                           ;; read, as `plaintext:price-as-
                                           ;; quoted` releases the one it makes.
                                           ;; The prices in `found` belong to
                                           ;; the list and go with it.
                                           (let* ((other (gnc-price-invert price))
                                                  (value (gnc-price-get-value other)))
                                             (gnc-price-unref other)
                                             value)))
                                      (plaintext:exact leg))))))))))))

;; Answers the price, or #f where nothing prices the pair. #f and not zero: a
;; line with no price states none, where a zero would read as "worth nothing",
;; which is a different claim and a false one beside a value GnuCash converted.
;;
;; `gnc:case-price-fn` from 4.4 on, and the same lookup built by hand where the
;; build has no such helper.
;;
;; Every source a statement is printed from reads the book's price database, so
;; the price on a line is one the book records. GnuCash's report also offers
;; `average-cost` and `weighted-average`, which price by a ratio of the book's
;; own transactions rather than by a recorded price; `services/gnucash_statements.py`
;; refuses those before a report is run, so nothing here has to answer for them.
(define (plaintext:price-fn source report-commodity moment)
  (if (defined? 'gnc:case-price-fn)
      (gnc:case-price-fn source report-commodity moment)
      (lambda (commodity)
        (plaintext:price-of-commodity commodity report-commodity moment source))))

;; A figure GnuCash computes that no account holds — unrealized gains, the
;; earnings of a year not yet closed — as a key of the block. One key whatever
;; the sign, where GnuCash's page switches between `Gains` and `Losses`: a
;; block is read by a program too, and the sign belongs in the figure.
;; Written as an account line writes a figure: the amount, then its commodity,
;; and no quotes. Quotes are for text — a name, a memo, a date — and a figure
;; in them reads as a string that happens to look like money. `value:` and
;; `share_price:` keep their quotes because those are the split attributes of
;; that name and a split writes them so.
(define (plaintext:computed depth name collector report-commodity exchange-fn)
  (string-append
   (plaintext:indent depth) name ": "
   (plaintext:amount
    (gnc:sum-collector-commodity collector report-commodity exchange-fn))))

;; The lines of one row of GnuCash's account table. Which balance the row
;; shows, its sign, and whether a foreign balance is shown beside its value,
;; are decided as `gnc:html-table-add-account-balances` decides them.
(define (plaintext:account-row env)
  (define (value key)
    (let ((found (assoc-ref env key)))
      (and found (car found))))
  (let* ((account (value 'account))
         (children (value 'account-children))
         (row-type (value 'row-type))
         (display-depth (value 'display-depth))
         (report-commodity (value 'report-commodity))
         (exchange-fn (value 'exchange-fn))
         (limit-behavior (or (value 'depth-limit-behavior) 'summarize))
         (parent-mode (or (value 'parent-account-balance-mode) 'omit-bal))
         (method
          (cond ((eq? row-type 'subtotal-row) 'recursive-bal)
                ((eqv? (1+ display-depth) (value 'display-tree-depth))
                 (cond ((eq? limit-behavior 'summarize) 'recursive-bal)
                       ((null? children) 'immediate-bal)
                       (else parent-mode)))
                ((not (null? children)) parent-mode)
                (else 'immediate-bal)))
         (collector (case method
                      ((immediate-bal) (value 'account-bal))
                      ((recursive-bal) (value 'recursive-bal))
                      (else #f)))
         (depth (or (value 'block-depth) 1))
         (price-fn (value 'price-fn)))
    (cond
     ;; A subtotal row is a parent's running total, which the HTML table shows
     ;; because its rows are indented. Every line here carries its account's
     ;; full path and its own balance, so the parent is a line of its own and a
     ;; subtotal would state the same figure twice.
     ((eq? row-type 'subtotal-row) '())
     ((or (not collector)
          (and (eq? (value 'zero-balance-display-mode) 'omit-balance)
               (gnc-commodity-collector-allzero? collector)))
      '())
     ;; An account holding nothing over the period is left off, which is this
     ;; page's own choice rather than GnuCash's: with its shipped defaults —
     ;; "Include accounts with zero total balances" on — GnuCash's page prints
     ;; such an account with a zero figure, measured on 5.10 for the year
     ;; ending 2026-03-31, which shows `Realized FX Gains`, `Realized Gains`
     ;; and `Interest`, none of which that year touched.
     ;;
     ;; The check is on what the collector holds, so an account whose entries
     ;; cancel each other out exactly is left off with them: a receivable
     ;; collected in full within the period is off the page as surely as one
     ;; nobody billed. An account holding money the report cannot price stays
     ;; on it — the collector holds that money, whatever value the price
     ;; database puts on it, and the line states it beside `value: "0.00"`.
     ;;
     ;; The line a block would write for it says nothing twice over: the figure
     ;; is zero, and an empty collector knows no commodity, so the amount comes
     ;; out in the block's own currency — a US dollar account reading
     ;; `0.00 CAD`, and a holding of shares reading `0.00 CAD` on a date before
     ;; any were bought. A column page can afford a row that only lines up a
     ;; heading; a block is read by a program, where `0.00 CAD` on a USD
     ;; account is a statement about the account that is not true.
     ((gnc-commodity-collector-allzero? collector) '())
     (else
      (let ((signed (if (gnc-reverse-balance account)
                        (gnc:commodity-collector-get-negated collector)
                        collector))
            (full-name (plaintext:full-name account)))
        ;; Every account's line is what that account itself holds, parents
        ;; included, which is what GnuCash's own page prints. Measured on 5.10,
        ;; a brokerage holding 3,000.00 USD of its own with a share account
        ;; under it:
        ;;
        ;;     Brokerage        $3,000.00   C$4,200.00
        ;;         AMZN          10 AMZN    C$3,640.00
        ;;     Total Assets                C$21,340.00
        ;;
        ;; The parent's row is its own balance in its own commodity, and the
        ;; sum lives in a `Total …` row. Reading the recursive balance onto the
        ;; parent's line instead printed `Assets:Brokerage 7840.00 CAD` — a
        ;; figure on no row of GnuCash's page — and lost both the US dollars
        ;; and the price they were converted at. Where the book prices nothing,
        ;; the same line read `0.00 CAD` for real money.
        ;;
        ;; A parent that holds nothing itself is left off by the zero check
        ;; above, as `Assets` and `Equity` are: GnuCash prints `Assets C$0.00`
        ;; for a placeholder, and a block that states a total under its own path
        ;; would be stating a figure the accounts beneath it already carry.
        (if (not (gnc:uniform-commodity? signed report-commodity))
            ;; Held in something other than the report's currency: the line
            ;; states what the account holds, and under it the commodity, the
            ;; price GnuCash priced it at and the value GnuCash made of it.
            (let loop ((balances (signed 'format gnc:make-gnc-monetary #f))
                       (lines '()))
              (if (null? balances)
                  (reverse lines)
                  (let* ((held (car balances))
                         (commodity (gnc:gnc-monetary-commodity held))
                         (price (price-fn commodity)))
                    (loop (cdr balances)
                          (append
                           (list
                            ;; `value:` is the split attribute of that name and
                            ;; is written as a split writes it: the figure in
                            ;; the currency the block is in, with no unit of
                            ;; its own, which `currency.mnemonic:` above states
                            ;; once for the whole block.
                            (plaintext:key
                             (+ depth 1) "value"
                             (plaintext:figure
                              (gnc:gnc-monetary-amount
                               (exchange-fn held report-commodity))
                              (plaintext:places-of report-commodity))))
                           ;; Only where the book holds one in the report's
                           ;; currency. A line with no price states none: zero
                           ;; would read as "worth nothing", which is a
                           ;; different claim and a false one beside a value
                           ;; GnuCash converted. `gnc:case-price-fn` answers
                           ;; zero rather than nothing for a commodity the book
                           ;; prices nowhere, so the figure is checked as well
                           ;; as the lookup.
                           (if (and price (not (gnc-numeric-zero-p price)))
                               (list (plaintext:key
                                      (+ depth 1) "share_price"
                                      (plaintext:figure price 0)))
                               '())
                           (list
                            (plaintext:key
                             (+ depth 1) "account.commodity.mnemonic"
                             (gnc-commodity-get-mnemonic commodity))
                            (plaintext:account-line
                             depth full-name (plaintext:amount held)))
                           lines)))))
            (list (plaintext:account-line
                   depth full-name
                   (plaintext:amount
                    (gnc:sum-collector-commodity
                     signed report-commodity exchange-fn))))))))))

;; Every line of GnuCash's account table for `accounts`.
(define (plaintext:account-lines table-env params accounts)
  (let ((table (gnc:make-html-acct-table/env/accts table-env accounts)))
    (let loop ((row (1- (gnc:html-acct-table-num-rows table)))
               (lines '()))
      (if (negative? row)
          lines
          (loop (1- row)
                (append (plaintext:account-row
                         (append (gnc:html-acct-table-get-row-env table row) params))
                        lines))))))

;; What a reader needs in order to read the block, and no more.
;;
;; Four lines, because these are printed on every page this tool draws. The
;; format is README's to explain and `docs/multi-currency.md`'s to work
;; through; a page that explains itself at length buries the figures a reader
;; opened it for. It ran to thirteen lines here and another thirty under the
;; the gain figures, which is longer than the statement on a small book.
;;
;; `share_price:` and `value:` earn their two lines: a split carries the same
;; two keys meaning something else — the rate a transaction happened at rather
;; than a valuation this report made on its own date — and nothing else on the
;; page tells the two apart.
;;
;; Indented inside the block rather than written above it, because a line at
;; column 0 is where a block's dated directive lives and anything looking for
;; one would find these instead. `#` because that is what this tool already
;; prepends to a printed invoice's caveats (Q-019), so every line it writes for
;; a reader rather than for a book looks the same.
(define plaintext:notes
  (list "# An account line is that account's own balance — never its children's."
        "# A section total, and any figure no account holds, is a key."
        "# share_price: and value: under an account line are what this report"
        "# valued the holding at on this date, not the rate a split happened at."))

;; What a reader cannot work out from the gain figures themselves: which of them
;; reaches the equity total, and which figure is GnuCash's rather than this
;; tool's. Everything else about them — how each is measured, what a currency
;; whose cost bases disagree with its accounts falls back to — is
;; `docs/multi-currency.md`'s to say, and saying it here again cost thirty
;; lines on every balance sheet drawn.
;;
;; The balance sheet's alone: the income statement states none of these keys,
;; and a page that explained keys it does not carry sent a reader looking for
;; figures that are not there — worse, it called `gnucash_balancing_amount`
;; "the last key" on a page whose last key is `net_income`, and said of it
;; "Nothing adds it in", which is untrue of that one. Q-043 says these lines
;; are added only where they mean something.
(define plaintext:gain-notes
  (list "#"
        "# A gain already taken is stated apart from one the book has yet to"
        "# take, and only the unrealized total reaches total_equity."
        "# gnucash_balancing_amount is GnuCash's own figure, carried across so"
        "# the two can be read against each other, and added into nothing."))

;; The currency the book is kept in, as gnucash-plaintext works it out, set
;; before the report runs. #f where nothing set it — GnuCash's own report
;; chooser, or this file run by hand — and the report's currency then stands
;; for it.
(define plaintext:book-currency #f)

(define (plaintext:set-book-currency! mnemonic)
  (set! plaintext:book-currency mnemonic))

(define (plaintext:own-commodity report-commodity)
  (or (and plaintext:book-currency
           (gnc-commodity-table-lookup
            (gnc-commodity-table-get-table (gnc-get-current-book))
            "CURRENCY" plaintext:book-currency))
      report-commodity))

;; The income and expense accounts kept in a commodity that is not the book's
;; own, which gnucash-plaintext does not support: a balance is a sum of amounts
;; from many days, each with a rate of its own, and no one rate converts it. The
;; page is still drawn, and the warning says which figures carry the error.
(define (plaintext:kept-in-another-currency accounts own)
  (filter (lambda (account)
            (not (gnc-commodity-equiv (xaccAccountGetCommodity account) own)))
          accounts))

;; Both warnings a page can open with. The first is about the book: an income
;; or expense account kept in a currency that is not its own. The second is
;; about the page: one drawn in a currency that is not the book's converts
;; every income and expense account at its own date's rate, which is the same
;; fault reached from the other side, and the advice for it is to draw the page
;; in the book's currency, not to move the accounts.
(define (plaintext:currency-warning accounts report-commodity)
  (let ((own (plaintext:own-commodity report-commodity)))
    (append (plaintext:account-currency-warning accounts own)
            (plaintext:page-currency-warning accounts own report-commodity))))

(define (plaintext:page-currency-warning accounts own report-commodity)
  (if (or (null? accounts) (gnc-commodity-equiv own report-commodity))
      '()
      (let ((base (gnc-commodity-get-mnemonic own))
            (page (gnc-commodity-get-mnemonic report-commodity)))
        (list "# ############################ WARNING ############################"
              (string-append "# This page is drawn in " page ", and the book is kept in "
                             base ".")
              "#"
              "# Every income and expense account is converted at the rate of the"
              "# page's own date. Its balance is a sum of amounts from many days,"
              "# each of which had a rate of its own, so every figure on this page"
              "# those accounts reach can be wrong."
              "#"
              (string-append "# Draw the page in " base " for those figures to be right.")
              "# #################################################################"
              "#"))))

(define (plaintext:account-currency-warning accounts own)
  (let ((wrong (plaintext:kept-in-another-currency accounts own))
        (base (gnc-commodity-get-mnemonic own)))
    (if (null? wrong)
        '()
        (append
         (list "# ############################ WARNING ############################"
               (string-append "# These income and expense accounts are not kept in " base ":")
               "#")
         (map (lambda (account)
                (string-append "#   " (plaintext:full-name account) " — "
                               (gnc-commodity-get-mnemonic
                                (xaccAccountGetCommodity account))))
              wrong)
         (list
          "#"
          "# gnucash-plaintext does not support that, and every figure on this"
          "# page those accounts reach can be wrong."
          "#"
          "# An expense is what it cost on the day it was incurred, and a rate"
          "# that moves afterwards does not change it. The balance of one of"
          "# these accounts is a sum of amounts from many days, and each of"
          "# those days had a rate of its own. No one rate turns that sum"
          (string-append "# into " base ". This page converts it at the rate of its own date,")
          "# so a page drawn a month later states that expense differently."
          "#"
          "# The account line states what the account holds in its own"
          "# currency, and the rate this page converted it at, so a reader who"
          "# knows what each amount cost on its own day can work the right"
          "# figure out for themselves."
          "#"
          (string-append "# Keep an income or expense account in " base ". Record a payment")
          "# made in another currency at what that currency cost on the day it"
          "# was spent."
          "# #################################################################"
          "#")))))

;; The block: its dated directive, what its keys mean, then its lines. `notes`
;; is what this statement has to explain — every page shares `plaintext:notes`,
;; and the balance sheet adds `plaintext:gain-notes` to them.
(define (plaintext:page-explaining notes directive lines)
  (string-append
   directive "\n"
   (string-join (map (lambda (note) (string-append (plaintext:indent 1) note))
                     notes)
                "\n")
   "\n"
   (string-join lines "\n") "\n"))

(define (plaintext:page directive lines)
  (plaintext:page-explaining plaintext:notes directive lines))

(define (plaintext:no-accounts directive)
  (plaintext:page directive
                  (list (plaintext:key 1 "accounts" "none selected"))))

;; The options every account table takes, as GnuCash's renderers pass them.
(define (plaintext:table-env option start end report-commodity exchange-fn)
  (let ((depth-limit (option "Accounts" "Levels of Subaccounts")))
    (list (list 'start-date start)
          (list 'end-date end)
          ;; Every account in the tree, whatever "Levels of Subaccounts" says.
          ;;
          ;; GnuCash's statements default that option to 3, and at the limit
          ;; its account table folds the deepest account into its parent and
          ;; lists it nowhere: measured on 5.10, a book whose `Assets:Bank:
          ;; Chequing` holds 300.00 CAD with 700.00 in `…:Chequing:Payroll`
          ;; prints one row, `Chequing C$1,000.00`, and no Payroll row at all.
          ;;
          ;; On a column page that is a reading convenience — the total is
          ;; right and a person can raise the limit. In a block it is an
          ;; account that does not appear, and a line that states its
          ;; children's money as its own, which is what every other line here
          ;; promises it never does. A block is read by a program, so it lists
          ;; what the book holds.
          (list 'display-tree-depth (gnc:get-current-account-tree-depth))
          (list 'depth-limit-behavior
                (if (option "Accounts" "Flatten list to depth limit") 'flatten 'summarize))
          (list 'report-commodity report-commodity)
          (list 'exchange-fn exchange-fn)
          (list 'parent-account-subtotal-mode
                (plaintext:subtotal-mode (option "Display" "Parent account subtotals")))
          (list 'zero-balance-mode
                (if (option "Display" "Include accounts with zero total balances")
                    'show-leaf-acct
                    'omit-leaf-acct))
          (list 'account-label-mode 'name))))

(define (plaintext:params option price-fn)
  ;; A parent account's line is its own balance, as GnuCash's page prints it:
  ;; a brokerage holding 3,000.00 USD with a share account under it shows
  ;; `Brokerage $3,000.00 C$4,200.00`, its own money in its own commodity, and
  ;; the sum of the section is a `Total …` row rather than anything written on
  ;; the parent. With the recursive balance instead, that line read
  ;; `Assets:Brokerage 7840.00 CAD`, a figure on no row of GnuCash's page, with
  ;; the currency it holds and the price it was valued at both gone.
  (list (list 'parent-account-balance-mode 'immediate-bal)
        (list 'zero-balance-display-mode
              (if (option "Display" "Omit zero balance figures") 'omit-balance 'show-balance))
        (list 'rule-mode #f)
        ;; Every account line sits one tab inside the block.
        (list 'block-depth 1)
        (list 'price-fn price-fn)))

;; balance-sheet.scm, `balance-sheet-renderer`.
(define (plaintext:balance-sheet-renderer report-obj)
  (define (option section name) (plaintext:option report-obj section name))
  (let* ((book (gnc-get-current-book))
         (moment (gnc:time64-end-day-time
                  (gnc:date-option-absolute-time
                   (option "General" "Balance Sheet Date"))))
         (accounts (option "Accounts" "Accounts"))
         ;; The block's directive: the date it is as of, then what it is. ISO,
         ;; as every date this format writes is — `qof-print-date` follows the
         ;; locale of whoever ran the command (CLAUDE.md finding 15).
         (title (string-append (gnc-print-time64 moment "%Y-%m-%d") " balance-sheet")))
    (if (null? accounts)
        (plaintext:no-accounts title)
        (let* ((use-trading-accounts? (qof-book-use-trading-accounts book))
               (report-commodity (option "Commodities" "Report's currency"))
               (exchange-fn (gnc:case-exchange-fn
                             (option "Commodities" "Price Source")
                             report-commodity moment))
               (split-up (gnc:decompose-accountlist accounts))
               (asset-accounts (assoc-ref split-up ACCT-TYPE-ASSET))
               (liability-accounts (assoc-ref split-up ACCT-TYPE-LIABILITY))
               (income-expense-accounts
                (append (assoc-ref split-up ACCT-TYPE-INCOME)
                        (assoc-ref split-up ACCT-TYPE-EXPENSE)))
               (equity-accounts (assoc-ref split-up ACCT-TYPE-EQUITY))
               (trading-accounts (assoc-ref split-up ACCT-TYPE-TRADING))

               (asset-balance (plaintext:balance-as-of asset-accounts moment))
               (liability-balance
                (gnc:commodity-collector-get-negated
                 (plaintext:balance-as-of liability-accounts moment)))
               (equity-balance
                (gnc:commodity-collector-get-negated
                 (plaintext:balance-as-of equity-accounts moment)))
               (retained-earnings
                (gnc:commodity-collector-get-negated
                 (plaintext:balance-as-of income-expense-accounts moment)))
               (trading-balance
                (if use-trading-accounts?
                    (gnc:commodity-collector-get-negated
                     (plaintext:balance-as-of trading-accounts moment))
                    (plaintext:collector)))
               ;; What the foreign money the book holds is worth today, less
               ;; what it cost. GnuCash's own Balance Sheet asks the second
               ;; question of the account's split values, which answer it only
               ;; where every split was valued in the book's currency — and an
               ;; invoice collected into a foreign bank is valued in the
               ;; foreign one, so there is no such figure to read. Measured on
               ;; a book holding 2,720.00 USD bought at 189557/136000 CAD/USD:
               ;; GnuCash omitted the gain and its sheet did not balance, and
               ;; on the same book with the money spent it stated the realized
               ;; loss over again as an unrealized gain of the opposite sign,
               ;; on an account holding nothing.
               ;;
               ;; So the cost comes from the book's own cost bases, which is
               ;; what `fx-balances` reports and what every disposal is
               ;; measured against. gnucash-plaintext calls
               ;; `plaintext:set-cost-basis-items!` before the report runs,
               ;; one row per cost basis.
               ;;
               ;; The two keys divide by what the money is, never by who
               ;; measured it: a currency that is not the book's own is `_fx`,
               ;; and a security is `_other`. Within `_fx` the book's own cost
               ;; bases are preferred, and a currency they cannot speak for
               ;; keeps GnuCash's own revaluation — GnuCash's own report
               ;; chooser leaves the list empty, a borrowing opens a cost basis
               ;; on neither side, and a disposal that states no cost basis guid
               ;; leaves a balance that is not what the book owns. Sorting
               ;; those into `_other` would state an exchange loss on the key
               ;; that says it is not one: a US dollar loan borrowed with
               ;; Canadian dollars is an exchange loss however it was measured.
               ;; At the smallest unit the report's currency divides into, like
               ;; every other gain on the page. A book using trading accounts
               ;; states none of these.
               (realized-fx
                (if use-trading-accounts?
                    0
                    (plaintext:as-money (plaintext:exact plaintext:realized-fx)
                                        report-commodity)))
               (holdings (append asset-accounts liability-accounts))
               ;; GnuCash's own revaluation of these accounts: what they are
               ;; worth at the price nearest this date, less the sum of their
               ;; split values.
               ;; GnuCash's revaluation of a set of accounts, as the two terms
               ;; it subtracts rather than as their difference: what the
               ;; accounts hold, and what their splits were recorded at, each
               ;; converted and each at the report currency's smallest unit.
               ;;
               ;; Two terms because a commodity measured this way states them
               ;; on the page as `value` and `cost_value`, exactly as one
               ;; measured from its cost bases does. The block's totals then
               ;; stay `value - cost_value` however each commodity was
               ;; measured, and none of them arrives as an addend of its own —
               ;; the comment on that line states the equation the block is,
               ;; and it has to hold.
               ;;
               ;; Each term rounded before they are subtracted, which is the
               ;; rule every gain on this page follows: rounding the difference
               ;; instead, while the lines beneath round their own two terms,
               ;; put the key and its items a cent apart whenever worth and
               ;; cost both landed between cents.
               (gnucash-worth-and-cost
                (lambda (accounts)
                  (cons (plaintext:as-money
                         (plaintext:converted
                          (plaintext:balance-as-of accounts moment)
                          report-commodity exchange-fn)
                         report-commodity)
                        (plaintext:as-money
                         (plaintext:converted
                          (gnc:accounts-get-comm-total-assets
                           accounts
                           (lambda (account)
                             (gnc:account-get-comm-value-at-date account moment #f)))
                          report-commodity exchange-fn)
                         report-commodity))))
               ;; The same figure commodity by commodity, each at the report
               ;; currency's smallest unit, so a key is the sum of figures a
               ;; reader can check one commodity at a time.
               ;;
               ;; A commodity at a time is also how GnuCash converts, which is
               ;; what keeps the key agreeing with `total_assets`: it takes the
               ;; whole holding through the price once. Account by account, two
               ;; brokerages each holding one share worth 10.005 came to 0.00
               ;; apiece where GnuCash converted the pair to 20.01, and the
               ;; sheet stated 1000.01 of assets against 1000.00 of liabilities
               ;; and equity. Asked of the whole list at once it would balance
               ;; and the working would not add up, which is the same fault
               ;; wearing the other face.
               (gnucash-revaluation-by-commodity
                (lambda (accounts)
                  (let loop ((rest (plaintext:commodities-of accounts)) (total 0))
                    (if (null? rest)
                        total
                        (loop (cdr rest)
                              (+ total
                                 (let ((parts (gnucash-worth-and-cost
                                               (plaintext:holding accounts
                                                                  (car rest)))))
                                   (- (car parts) (cdr parts)))))))))
               ;; One side of the sheet's foreign currency, measured from that
               ;; side's own cost bases where their balance matches what it
               ;; holds, and from GnuCash's own revaluation for the rest.
               ;;
               ;; Each side is money at the report currency's smallest unit
               ;; before they are added, so the two figures on the page come to
               ;; the third exactly. Added first and rounded once, they could
               ;; differ from their own total by a cent, and a reader adding up
               ;; three printed lines would find them wrong.
               (side-fx
                (lambda (side accounts)
                  (if use-trading-accounts?
                      0
                      (plaintext:as-money
                       (+ (plaintext:revaluation
                           (plaintext:price-fn (option "Commodities" "Price Source")
                                               report-commodity moment)
                           side accounts moment report-commodity "CURRENCY")
                          (gnucash-revaluation-by-commodity
                           (plaintext:fallback-accounts
                            side accounts moment report-commodity)))
                       report-commodity))))
               ;; Each side's foreign currency is what is held or owed on it,
               ;; whatever type of account it sits in.
               (held-accounts (plaintext:on-the-side-of-its-balance
                               "asset" asset-accounts liability-accounts moment))
               (owed-accounts (plaintext:on-the-side-of-its-balance
                               "liability" asset-accounts liability-accounts moment))
               (unrealized-assets-fx (side-fx "asset" held-accounts))
               (unrealized-liabilities-fx (side-fx "liability" owed-accounts))
               (unrealized-fx (+ unrealized-assets-fx unrealized-liabilities-fx))
               ;; An account held in the book's own currency takes no part in
               ;; either key. Reading GnuCash's reconstruction for one charged
               ;; a Canadian account 19.86 that was neither a gain nor a loss:
               ;; its splits sat in US dollar transactions, so their values
               ;; summed to nothing and the whole balance read as a movement.
               ;;
               ;; Commodity by commodity, as `plaintext:securities-block`
               ;; prints them beneath it and as GnuCash itself converts: a
               ;; holding's whole quantity goes through the price once, which
               ;; is the figure `total_assets` carries. Account by account the
               ;; remainders are rounded away separately — one share worth
               ;; 10.005 in each of two brokerages came to 0.00 twice where
               ;; GnuCash converted the pair to 20.01 — and the sheet stopped
               ;; balancing on a book holding no foreign currency at all.
               ;; Measured from the security's own cost bases where they
               ;; account for what the accounts hold, and from GnuCash's
               ;; revaluation for the rest — the same two-part answer the two
               ;; `_fx` keys above state, because a share is a holding with a
               ;; cost like any other (Q-046).
               ;;
               ;; What the two differ over is which day's rate the cost is
               ;; converted at. GnuCash takes the summed split values, which for
               ;; a purchase written in US dollars is a US dollar figure, and
               ;; converts it at the sheet's own rate — putting today's rate on
               ;; the cost as well as on the worth, which cancels the currency
               ;; out of the gain and leaves the share's own movement alone. A
               ;; cost basis holds what the units cost in the book's currency on
               ;; the day they were bought, and never moves again: 100 shares
               ;; bought for 10,000.00 USD when the dollar stood at 1.40 cost
               ;; 14,000.00 CAD, so a sheet drawn at 1.25 with the share at
               ;; 150.00 USD states a gain of 4,750.00 where GnuCash's
               ;; subtraction states 6,250.00 — and the page balances on the
               ;; first and not on the second.
               (unrealized-other
                (if use-trading-accounts?
                    0
                    (let ((securities (plaintext:securities holdings)))
                      (plaintext:as-money
                       (+ (plaintext:revaluation
                           (plaintext:price-fn (option "Commodities" "Price Source")
                                               report-commodity moment)
                           "asset" securities moment report-commodity 'security)
                          (gnucash-revaluation-by-commodity
                           (plaintext:securities-gnucash-keeps securities moment)))
                       report-commodity))))
               (total-unrealized (+ unrealized-fx unrealized-other))
               ;; What the book's residual splits leave out of the realized
               ;; gain, over the same cost bases the unrealized keys are
               ;; measured from. Into equity beside them, because
               ;; `retained_earnings` carries only what the book recorded.
               (not-recorded-entries
                (if use-trading-accounts?
                    '()
                    (append (plaintext:realized-not-recorded
                             "asset" held-accounts moment report-commodity "CURRENCY")
                            (plaintext:realized-not-recorded
                             "liability" owed-accounts moment report-commodity "CURRENCY")
                            (plaintext:realized-not-recorded
                             "asset" (plaintext:securities holdings) moment
                             report-commodity 'security))))
               (realized-not-recorded
                (let sum ((xs not-recorded-entries) (total 0))
                  (if (null? xs)
                      total
                      (sum (cdr xs) (+ total (car (cdr (cdr (cdr (car xs))))))))))
               ;; The amount GnuCash calculates just to balance the book,
               ;; carried across as GnuCash states it so a reader can find the
               ;; same number on GnuCash's own page. Never added into anything.
               ;; The collector GnuCash's balancing amount is summed from, kept
               ;; rather than thrown away once summed, because the items
               ;; printed under that key are read out of it.
               ;;
               ;; **Itemizing shows how GnuCash reached its figure.** A
               ;; computation of this report's own, set beside it under the
               ;; same name, could agree with it only by luck — and did not:
               ;; grouping by the currency each split's value is stated in left
               ;; out every commodity no split is valued in, so a book that
               ;; borrowed 1,000.00 USD stated 1300.00 under a key whose own
               ;; figure is -100.00.
               (gnucash-balancing-gains
                (let ((gains (plaintext:collector)))
                  (if (not use-trading-accounts?)
                      (begin
                        (gains 'merge asset-balance #f)
                        (gains 'minusmerge liability-balance #f)
                        (gains 'minusmerge
                               (gnc:accounts-get-comm-total-assets
                                (append asset-accounts liability-accounts)
                                (lambda (account)
                                  (gnc:account-get-comm-value-at-date account moment #f)))
                               #f)))
                  gains))
               (gnucash-balancing-amount
                (if use-trading-accounts?
                    0
                    (plaintext:as-money
                     (plaintext:exact
                      (gnc:gnc-monetary-amount
                       (gnc:sum-collector-commodity gnucash-balancing-gains
                                                    report-commodity exchange-fn)))
                     report-commodity)))
               ;; The equity total carries the gains the book measures for
               ;; itself, never GnuCash's balancing amount.
               ;;
               ;; GnuCash's amount is what is left when the summed split values
               ;; are taken from the converted balances. Where every split of a
               ;; holding carries a figure in the book's own currency that is
               ;; the revaluation gap, and putting it here would balance the
               ;; sheet. Where they do not it is something else, and putting it
               ;; here would unbalance the page — where a book's foreign
               ;; currency arrived carrying no figure in the book's own currency
               ;; and was later spent, GnuCash's amount comes out as the
               ;; negative of the gain or loss already taken, which is in the
               ;; income accounts and in `retained_earnings` already, so adding
               ;; it cancels that gain or loss rather than doubling it. Q-044
               ;; has the figures.
               ;; A split's value is stated in its
               ;; transaction's
               ;; currency, so for a book whose foreign transactions are
               ;; valued in the foreign currency that subtraction measures
               ;; nothing, and it restated a realized loss as an unrealized
               ;; gain on an account holding nothing. A sheet that balances on
               ;; a wrong figure is worse than one that does not balance,
               ;; because nothing on the page then says so.
               ;;
               ;; So the book's own figure goes here. It is a rational in the
               ;; report's currency rather
               ;; than a collector of commodities, so the accounts are
               ;; converted first and the two are added in that currency.
               (total-equity
                (+ (plaintext:exact
                    (gnc:gnc-monetary-amount
                     (gnc:sum-collector-commodity
                      (plaintext:collector equity-balance retained-earnings trading-balance)
                      report-commodity exchange-fn)))
                   total-unrealized
                   realized-not-recorded))
               (liabilities-and-equity
                (+ (plaintext:exact
                    (gnc:gnc-monetary-amount
                     (gnc:sum-collector-commodity liability-balance
                                                  report-commodity exchange-fn)))
                   total-equity))

               (table-env (plaintext:table-env option #f moment report-commodity exchange-fn))
               (price-fn (plaintext:price-fn (option "Commodities" "Price Source")
                                             report-commodity moment))
               (params (plaintext:params option price-fn))
               (computed (lambda (name collector)
                           (plaintext:computed 1 name collector
                                               report-commodity exchange-fn)))
               ;; A key states a figure GnuCash computed, and a figure of zero
               ;; states nothing: a book whose holdings have moved not at all
               ;; has no unrealized gain to report, and a year with no income
               ;; and no expenses has no earnings retained. So the key is left
               ;; off rather than written as `0.00`.
               ;;
               ;; The question is whether the book holds any such money, not
               ;; what it converts to. Asking the converted total instead hid
               ;; the key whenever the money could not be priced: a CAD book
               ;; whose income and expenses are all in US dollars, with no USD
               ;; price recorded, has retained earnings that convert to 0.00
               ;; CAD, and the page then said nothing about them at all. An
               ;; account line in that position states `value: "0.00"`, so a
               ;; reader sees money valued at nothing; a key that vanishes
               ;; tells them there was none.
               ;;
               ;; So a collector holding nothing loses its key, and one holding
               ;; money keeps it — including money whose commodities offset to
               ;; zero, a loan drawn and valued the same day, where `0.00` is
               ;; the true figure and GnuCash's own page prints that row too.
               (unless-zero (lambda (collector line)
                              (if (gnc-commodity-collector-allzero? collector)
                                  '()
                                  (list line)))))
          ;; Each section's accounts, then its total, in the order GnuCash's own
          ;; page puts them: every account line is what that account itself
          ;; holds, so a section's total is a figure no account holds and is
          ;; therefore a key of the block — `Total Assets`, `Total Liabilities`
          ;; and `Total Equity` on GnuCash's page, which a reader of either
          ;; needs to check the sheet balances.
          ;;
          ;; `total_equity` comes after the retained earnings, trading gains
          ;; and unrealized gains, and includes them, because GnuCash's Total
          ;; Equity row does: they are equity the book has earned or has yet to
          ;; realize, held in no equity account.
          ;; Those two lines go on a page that states a gain. A book using
          ;; trading accounts keeps its gains in its Trading accounts and
          ;; states `trading_gains` instead, printing neither `realized_gains_fx`
          ;; nor `gnucash_balancing_amount` — so the lines would explain
          ;; figures that are not there, and would tell a reader that two of
          ;; its totals differ from GnuCash's when neither does: measured on
          ;; such a book, 3,550.00 of liabilities and 34,982.80 of equity come
          ;; to the 38,532.80 it states, with no unrealized total in it. That
          ;; is the same fault as putting them on an income statement, one page
          ;; along.
          (plaintext:page-explaining
           (append
            (plaintext:currency-warning income-expense-accounts report-commodity)
            (if use-trading-accounts?
                plaintext:notes
                (append plaintext:notes plaintext:gain-notes
                        (if (null? not-recorded-entries)
                            '()
                            (list "# realized_gains_not_recorded reaches total_equity"
                                  "# as well: retained_earnings carries only the"
                                  "# realized gain the book recorded.")))))
           title
           (append
            (list (plaintext:key 1 "currency.mnemonic"
                                 (gnc-commodity-get-mnemonic report-commodity)))
            (plaintext:account-lines table-env params asset-accounts)
            (list (computed "total_assets" asset-balance))
            (plaintext:account-lines table-env params liability-accounts)
            (list (computed "total_liabilities" liability-balance))
            (plaintext:account-lines table-env params equity-accounts)
            (unless-zero retained-earnings
                         (computed "retained_earnings" retained-earnings))
            (unless-zero trading-balance
                         (computed "trading_gains" trading-balance))
            ;; The foreign-currency figure, the total, then GnuCash's own
            ;; amount. Each is money at the report currency's own unit, and
            ;; each states what it is: `_fx` is measured against the book's
            ;; cost bases, and the balancing amount is GnuCash's, stated so a
            ;; reader can reconcile against GnuCash's own page and added into
            ;; nothing here.
            ;;
            ;; None of them on a book that uses trading accounts. GnuCash books
            ;; the revaluation into accounts of its own there, so the money is
            ;; an account balance and `trading_gains` above states it; a page
            ;; carrying both would state the same gain twice, and Q-042 has it
            ;; that a book has one or the other and never both.
            ;;
            ;; `realized_gains_fx` and `total_realized_gains` are written from
            ;; the splits a `$residual$` resolved to, which gnucash-plaintext
            ;; marks as it imports them: what a disposal fetched is on the
            ;; splits facing it, and nothing in a saved transaction could be
            ;; asked afterwards which of those was the exchange difference. A
            ;; trading-accounts book states none of these keys either, for the
            ;; same reason it states none of the unrealized ones.
            (if use-trading-accounts?
                '()
                (append
                 (if plaintext:itemize?
                     (plaintext:cost-basis-block price-fn report-commodity moment
                                                 held-accounts
                                                 gnucash-worth-and-cost)
                     (list (string-append
                            (plaintext:indent 1) "unrealized_gains_assets_fx: "
                            (plaintext:amount-of unrealized-assets-fx
                                                 report-commodity))))
                 (list (string-append
                        (plaintext:indent 1) "unrealized_gains_liabilities_fx: "
                        (plaintext:amount-of unrealized-liabilities-fx
                                             report-commodity))
                       (string-append
                        (plaintext:indent 1) "unrealized_gains_fx: "
                        (plaintext:amount-of unrealized-fx report-commodity)
                        " # unrealized_gains_assets_fx +"
                        " unrealized_gains_liabilities_fx"))
                 (if plaintext:realized-known?
                     (append
                      (if plaintext:itemize?
                          (plaintext:realized-block report-commodity)
                          (list (string-append
                                 (plaintext:indent 1) "realized_gains_fx: "
                                 (plaintext:amount-of realized-fx report-commodity))))
                      ;; Stated at the report's own commodity and places, as
                      ;; every other key no account holds is, rather than as a
                      ;; bare `0`: `total_realized_gains` below adds it in, so
                      ;; it is a figure of zero in that currency and not the
                      ;; absence of one.
                      (list (string-append
                             (plaintext:indent 1) "realized_gains_other: "
                             (plaintext:amount-of plaintext:realized-other
                                                  report-commodity))
                            (string-append
                             (plaintext:indent 1) "total_realized_gains: "
                             (plaintext:amount-of (+ realized-fx
                                                     plaintext:realized-other)
                                                  report-commodity)
                             " # realized_gains_fx + realized_gains_other")))
                     '())
                 (if plaintext:itemize?
                     (plaintext:securities-block (plaintext:securities holdings)
                                                 price-fn report-commodity moment
                                                 exchange-fn)
                     (list (string-append
                            (plaintext:indent 1) "unrealized_gains_other: "
                            (plaintext:amount-of unrealized-other report-commodity))))
                 (list (string-append
                        (plaintext:indent 1) "total_unrealized_gains: "
                        (plaintext:amount-of total-unrealized report-commodity)
                        " # unrealized_gains_fx + unrealized_gains_other"))
                 ;; Only where there is one: a book whose disposals were each
                 ;; valued at what is left of their cost records its realized
                 ;; gain whole, and a zero here would state nothing.
                 (cond ((null? not-recorded-entries) '())
                       (plaintext:itemize?
                        (plaintext:not-recorded-block not-recorded-entries
                                                      report-commodity))
                       (else
                        (list (string-append
                               (plaintext:indent 1) "realized_gains_not_recorded: "
                               (plaintext:amount-of realized-not-recorded report-commodity)
                               " # what the disposals' values, each rounded to the"
                               " cent, leave out of the realized gain the book"
                               " records"))))
                 (if plaintext:itemize?
                     (plaintext:balancing-block holdings moment report-commodity
                                                exchange-fn price-fn
                                                gnucash-balancing-gains)
                     (list (string-append
                            (plaintext:indent 1) "gnucash_balancing_amount: "
                            (plaintext:amount-of gnucash-balancing-amount
                                                 report-commodity))))))
            (list (string-append
                   (plaintext:indent 1) "total_equity: "
                   (plaintext:amount-of total-equity report-commodity)))
            (list (string-append
                   (plaintext:indent 1) "total_liabilities_and_equity: "
                   (plaintext:amount-of liabilities-and-equity report-commodity)))))))))

;; income-statement.scm, `income-statement-renderer-internal`.
(define (plaintext:income-statement-renderer report-obj)
  (define (option section name) (plaintext:option report-obj section name))
  (let* ((start-printable (gnc:date-option-absolute-time (option "General" "Start Date")))
         (start (gnc:time64-start-day-time start-printable))
         (end (gnc:time64-end-day-time
               (gnc:date-option-absolute-time (option "General" "End Date"))))
         (accounts (option "Accounts" "Accounts"))
         ;; The block's directive: the day the period starts, then what it is.
         ;; Its end is a key below, as a period needs both. ISO, as every date
         ;; this format writes is — `qof-print-date` follows the locale of
         ;; whoever ran the command (CLAUDE.md finding 15).
         (title (string-append (gnc-print-time64 start-printable "%Y-%m-%d")
                               " income-statement")))
    (if (null? accounts)
        (plaintext:no-accounts title)
        (let* ((report-commodity (option "Commodities" "Report's currency"))
               (exchange-fn (gnc:case-exchange-fn
                             (option "Commodities" "Price Source")
                             report-commodity end))
               (closing-pattern
                (list (list 'str (option "Entries" "Closing Entries pattern"))
                      (list 'cased (option "Entries" "Closing Entries pattern is case-sensitive"))
                      (list 'regexp (option "Entries" "Closing Entries Pattern is regular expression"))
                      (list 'closing #t)))
               (split-up (gnc:decompose-accountlist accounts))
               (revenue-accounts (assoc-ref split-up ACCT-TYPE-INCOME))
               (trading-accounts (assoc-ref split-up ACCT-TYPE-TRADING))
               (expense-accounts (assoc-ref split-up ACCT-TYPE-EXPENSE))

               (expense-total
                (let ((total (plaintext:collector
                              (gnc:accountlist-get-comm-balance-interval-with-closing
                               expense-accounts start end))))
                  (total 'minusmerge
                         (gnc:account-get-trans-type-balance-interval-with-closing
                          expense-accounts closing-pattern start end)
                         #f)
                  total))
               (revenue-total
                (let ((total (plaintext:collector
                              (gnc:account-get-trans-type-balance-interval-with-closing
                               revenue-accounts closing-pattern start end))))
                  (total 'minusmerge
                         (gnc:accountlist-get-comm-balance-interval-with-closing
                          revenue-accounts start end)
                         #f)
                  total))
               (trading-total
                (gnc:accountlist-get-comm-balance-interval-with-closing
                 trading-accounts start end))
               (net-income
                (let ((total (plaintext:collector revenue-total trading-total)))
                  (total 'minusmerge expense-total #f)
                  total))

               (table-env (append (plaintext:table-env option start end
                                                       report-commodity exchange-fn)
                                  (list (list 'balance-mode 'pre-closing)
                                        (list 'closing-pattern closing-pattern))))
               (price-fn (plaintext:price-fn (option "Commodities" "Price Source")
                                            report-commodity end))
               (params (plaintext:params option price-fn)))
          ;; Each section's accounts, then its total, in the order GnuCash's own
          ;; page puts them: every account line is what that account itself
          ;; holds, so a section's total is a figure no account holds and is a
          ;; key of the block — `Total Revenue` and `Total Expenses` on
          ;; GnuCash's page, with `Net income` under them.
          ;;
          ;; No trading section. GnuCash's Income Statement selects income and
          ;; expense accounts and nothing else — `(list ACCT-TYPE-INCOME
          ;; ACCT-TYPE-EXPENSE)` in its own `income-statement.scm` on 3.8 and
          ;; 5.10 — so `trading-accounts` is empty even for a book that uses
          ;; them, and a trading section here would be a heading over nothing.
          ;; `trading-total` is still summed into the net income, as GnuCash
          ;; sums it, and a book's trading gains reach the reader through the
          ;; balance sheet's `trading_gains` key.
          (let ((computed (lambda (name collector)
                            (plaintext:computed 1 name collector
                                                report-commodity exchange-fn))))
            (plaintext:page-explaining
             (append (plaintext:currency-warning
                      (append revenue-accounts expense-accounts) report-commodity)
                     plaintext:notes)
             title
             (append
              (list (plaintext:key 1 "end" (gnc-print-time64 end "%Y-%m-%d"))
                    (plaintext:key 1 "currency.mnemonic"
                                   (gnc-commodity-get-mnemonic report-commodity)))
              (plaintext:account-lines table-env params revenue-accounts)
              (list (computed "total_revenue" revenue-total))
              (plaintext:account-lines table-env params expense-accounts)
              (list (computed "total_expenses" expense-total))
              (list (computed "net_income" net-income)))))))))

(gnc:define-report
 'version 1
 'name "Balance Sheet (plain text)"
 'report-guid "826cfa6cfe624263b4091d99483d9198"
 'options-generator (plaintext:options-of plaintext:balance-sheet-template)
 'renderer plaintext:balance-sheet-renderer)

(gnc:define-report
 'version 1
 'name "Income Statement (plain text)"
 'report-guid "6c442542374e4f178318bb5d456d3cf9"
 'options-generator (plaintext:options-of plaintext:income-statement-template)
 'renderer plaintext:income-statement-renderer)
