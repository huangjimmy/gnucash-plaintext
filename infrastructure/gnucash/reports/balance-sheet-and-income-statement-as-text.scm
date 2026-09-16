;; The balance sheet and income statement printed as plain text, by GnuCash
;; reports customized from GnuCash's own Balance Sheet and Income Statement.
;;
;; `balance-sheet`, `income-statement` and `report` load this file and run one
;; of these two reports for `--output-format text` (Q-042), so every figure on
;; the page is added up and converted by GnuCash, not by gnucash-plaintext.
;; Each is a GnuCash report like any other: registered with
;; `gnc:define-report`, run by GnuCash's report code, and given GnuCash's own
;; options, because its options generator is the Balance Sheet's or the Income
;; Statement's, found by guid.
;;
;; The figures come from the calls GnuCash's own balance-sheet.scm and
;; income-statement.scm make, in the same order: each account's balance from
;; the engine, added up in GnuCash's commodity collectors, converted by
;; `gnc:case-exchange-fn` at the report's price source, and written by
;; `gnc:monetary->string`. Only the page is different. A renderer may return a
;; string, and `gnc:report-render-html` then returns that string unchanged,
;; with no style sheet and no HTML. Read on GnuCash 3.4, 3.8, 4.4 and 5.10.
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
;; GnuCash did not give. Padded to the commodity's own places, and written as
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

(define (plaintext:amount monetary)
  (let ((commodity (gnc:gnc-monetary-commodity monetary)))
    (string-append (plaintext:figure (gnc:gnc-monetary-amount monetary)
                                     (plaintext:places-of commodity))
                   " "
                   (gnc-commodity-get-mnemonic commodity))))

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
;; given stated 5 where a Hong Kong dollar is 0.2 of a Canadian one, beside a
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
;; Both halves are prices GnuCash gives, and they are multiplied as exact
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
        ;; would be stating a figure the accounts beneath it already give.
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

;; What the block's own keys mean, written into the page as comments.
;;
;; `share_price:` and `value:` are the names a split carries, and under an
;; account line they mean something else — a valuation the report made on its
;; own date, rather than the rate a transaction happened at. A reader meeting
;; the same two keys in both places would have no way to tell, so the page
;; says which it is.
;;
;; Indented inside the block rather than written above it, because a line at
;; column 0 is where a block's dated directive lives and anything looking for
;; one would find these instead.
;;
;; `#` because that is what this tool already prepends to a printed invoice's
;; caveats (Q-019), so every line it writes for a reader rather than for a book
;; looks the same.
(define plaintext:notes
  (list "# Every figure is GnuCash's own, from its Balance Sheet or Income"
        "# Statement report. An account line states what that account itself"
        "# holds — a parent's line is its own balance, not its children's."
        "# A section's total, and any figure no account holds, is a key."
        "#"
        "# share_price: and value: under an account line are what the report"
        "# valued that holding at on this date: the price read from the book's"
        "# price database, and what GnuCash converted the holding to. They are"
        "# not the keys of the same name on a transaction split, which record"
        "# the rate a transaction actually happened at and multiply out exactly."
        "# A price here changes with the date and with the book's prices; a"
        "# split's does not change at all."))

;; The block: its dated directive, what its keys mean, then its lines.
(define (plaintext:page directive lines)
  (string-append
   directive "\n"
   (string-join (map (lambda (note) (string-append (plaintext:indent 1) note))
                     plaintext:notes)
                "\n")
   "\n"
   (string-join lines "\n") "\n"))

(define (plaintext:no-accounts directive)
  (plaintext:page directive
                  (list (plaintext:key 1 "accounts" "none selected"))))

;; The options every account table is given, as GnuCash's renderers give them.
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
  ;; the parent. Given the recursive balance instead, that line read
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
               (unrealized-gains
                (let ((gains (plaintext:collector)))
                  (unless use-trading-accounts?
                    (gains 'merge asset-balance #f)
                    (gains 'minusmerge liability-balance #f)
                    (gains 'minusmerge
                           (gnc:accounts-get-comm-total-assets
                            (append asset-accounts liability-accounts)
                            (lambda (account)
                              (gnc:account-get-comm-value-at-date account moment #f)))
                           #f))
                  gains))
               (total-equity (plaintext:collector equity-balance retained-earnings
                                                  unrealized-gains trading-balance))
               (liabilities-and-equity (plaintext:collector liability-balance total-equity))

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
          (plaintext:page
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
            (unless-zero unrealized-gains
                         (computed "unrealized_gains" unrealized-gains))
            (list (computed "total_equity" total-equity))
            (list (computed "total_liabilities_and_equity"
                            liabilities-and-equity))))))))

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
            (plaintext:page
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
