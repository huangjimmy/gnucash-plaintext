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
;; totalled from the book's own cost bases. The empty list until somebody sets
;; it, and the balance sheet then falls back to GnuCash's own reconstruction.
;;
;; Set through a procedure rather than written into the variable from outside:
;; a `define` evaluated by gnucash-plaintext lands in whichever module it
;; evaluates in, which is not the one this file is loaded into, so the report
;; never saw it. A call resolves to the procedure here and its `set!` moves
;; this binding, whichever module the caller is in.
(define plaintext:cost-bases '())

(define (plaintext:set-cost-bases! bases)
  (set! plaintext:cost-bases bases))

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
;; Written as comments, so nothing that reads the block picks any of it up:
;; `#` opens a line the format skips, which is what lets the workings be added
;; without changing what a page means to a program.
(define plaintext:itemize? #t)

(define (plaintext:set-itemize! shown)
  (set! plaintext:itemize? shown))

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

;; One line per difference: when it was realized, where it was booked, and what
;; it came to. They add up to `realized_gains_fx`.
(define (plaintext:realized-workings report-commodity)
  (map (lambda (item)
         (string-append
          (plaintext:indent 1) "#   "
          (car item) " " (car (cdr item)) " "
          (plaintext:amount-of (car (cdr (cdr item))) report-commodity)))
       plaintext:realized-items))

;; How much of `commodity` the accounts given hold at `moment`.
;;
;; One side's accounts, never both: the balance sheet states a gain for the
;; currency it holds and for the currency it owes separately, and each side's
;; cost bases are checked against the holdings of that side alone. Handed both
;; at once a bank and a loan would net against each other, and a book holding
;; 7,480.00 USD against 2,500.00 USD owed would answer 4,980.00 — a figure
;; neither side's cost bases account for, so neither would match and both would
;; fall back to GnuCash's revaluation.
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
(define (plaintext:basis-matches-holdings? basis accounts moment table)
  (let ((commodity (gnc-commodity-table-lookup
                    table "CURRENCY" (plaintext:basis-mnemonic basis))))
    (and commodity
         (= (plaintext:held-in accounts commodity moment)
            (plaintext:basis-balance basis)))))

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
       ;; `plaintext:revaluation` and in `plaintext:cost-basis-workings` — and
       ;; every build draws the page 4.4 and later already drew.
       (let ((table (gnc-commodity-table-get-table (gnc-get-current-book)))
             (mnemonic (gnc-commodity-get-mnemonic commodity)))
         (let loop ((bases plaintext:cost-bases))
           (cond ((null? bases) #f)
                 ((and (string=? (plaintext:basis-mnemonic (car bases)) mnemonic)
                       (string=? (plaintext:basis-side (car bases)) side)
                       (plaintext:basis-matches-holdings?
                        (car bases) accounts moment table)) #t)
                 (else (loop (cdr bases))))))))

;; One cost basis's own gain, at the report currency's smallest unit: what its
;; remaining balance is worth at the report's price, less what that balance
;; cost, each term rounded to money before the subtraction.
;;
;; Both the key and the working line take the figure from here. Computed twice
;; they came to differ: rounding the difference for the key while the line
;; rounded its two terms put them a cent apart whenever worth and cost both
;; landed between cents — 333.33 USD at a cost of 189557/136000, priced at
;; 1.3865, is worth 462.162045 and cost 464.595844, which the line printed as
;; 462.16 less 464.60 = -2.44 while the key added -2.43. The page tells a
;; reader the lines add up to the key above them, so the two cannot be two
;; computations.
(define (plaintext:basis-gain basis exact-price report-commodity)
  (- (plaintext:as-money (* (plaintext:basis-balance basis) exact-price)
                         report-commodity)
     (plaintext:as-money (plaintext:basis-cost basis) report-commodity)))

;; One line showing how a currency's share of the figure was worked out: what
;; the book holds against its cost bases on this side, what that cost, the
;; price nearest the report's date, what it is worth at that price, and the
;; difference — which is what the key states.
;;
;; The balance is in its own currency and is written at that currency's places;
;; the cost, the worth and the difference are money in the report's. The price
;; is written exactly and never rounded to money: it is a rate, and 189557/136000
;; is a rate a book really holds.
;;
;; The cost is rounded before the difference is taken, so the line subtracts as
;; it is printed: `worth - cost = gain` holds between the three figures a reader
;; sees, rather than between two of them and an unrounded cost behind the third.
;; Left exact it printed `cost 189557/136 CAD` — a fraction no account can hold,
;; beside a difference nobody could check by eye.
(define (plaintext:basis-working basis commodity price report-commodity)
  (let* ((balance (plaintext:basis-balance basis))
         (cost (plaintext:as-money (plaintext:basis-cost basis) report-commodity))
         (exact-price (plaintext:exact price))
         (worth (plaintext:as-money (* balance exact-price) report-commodity))
         (gain (plaintext:basis-gain basis exact-price report-commodity)))
    (string-append
     (plaintext:indent 1) "#   "
     (plaintext:basis-side basis) " "
     (plaintext:figure balance (plaintext:places-of commodity)) " "
     (gnc-commodity-get-mnemonic commodity)
     " cost " (plaintext:amount-of cost report-commodity)
     ", at " (plaintext:figure exact-price 0)
     " worth " (plaintext:amount-of worth report-commodity)
     " = " (plaintext:amount-of gain report-commodity))))

;; Those lines for one side of the sheet, in the order the cost bases arrived.
(define (plaintext:cost-basis-workings side accounts moment price-fn report-commodity)
  (let ((table (gnc-commodity-table-get-table (gnc-get-current-book))))
    (let loop ((bases plaintext:cost-bases) (lines '()))
      (if (null? bases)
          (reverse lines)
          (let* ((basis (car bases))
                 (commodity (gnc-commodity-table-lookup
                             table "CURRENCY" (plaintext:basis-mnemonic basis)))
                 ;; A price of nothing where the book holds none: #f on 3.4 and
                 ;; 3.8, 0 from 4.4 on, and the line has to read the same on
                 ;; both. See `plaintext:measured-from-cost-bases?`.
                 (price (and commodity (or (price-fn commodity) 0))))
            (loop (cdr bases)
                  (if (and price
                           (string=? (plaintext:basis-side basis) side)
                           (plaintext:basis-matches-holdings?
                            basis accounts moment table))
                      (cons (plaintext:basis-working
                             basis commodity price report-commodity)
                            lines)
                      lines)))))))

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

;; One key's working: which key it is, then the items behind it. A key with
;; nothing behind it says so — "nothing" is an answer a reader can check, and
;; silence is not.
(define (plaintext:key-workings name items)
  (cons (string-append (plaintext:indent 1) "#")
        (cons (string-append (plaintext:indent 1) "# " name ":")
              (if (null? items)
                  (list (string-append (plaintext:indent 1) "#   nothing"))
                  items))))

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

;; GnuCash's own revaluation, commodity by commodity: what the book's whole
;; holding of each is worth at the nearest price, less the sum of its splits'
;; values. A commodity that comes to nothing is left out — every commodity of
;; the book would otherwise be listed, and a line of zero says only that it is
;; not part of this figure.
;;
;; By commodity and not by account, because that is how GnuCash converts: it
;; takes a holding's whole quantity through the price once, and `total_assets`
;; is that figure. Rounded account by account instead, the remainders are
;; rounded away separately and the key stops agreeing with the page it is on —
;; one share worth 10.005 in each of two brokerages came to 0.00 twice where
;; GnuCash converted the pair to 20.01, so a sheet stated 1000.01 of assets
;; against 1000.00 of liabilities and equity, with `nothing` printed under
;; every gain key because each zero line had been left out.
(define (plaintext:gnucash-workings accounts report-commodity revaluation)
  (let loop ((rest (plaintext:commodities-of accounts)) (lines '()))
    (if (null? rest)
        (reverse lines)
        (let ((figure (plaintext:as-money
                       (revaluation (plaintext:holding accounts (car rest)))
                       report-commodity)))
          (loop (cdr rest)
                (if (zero? figure)
                    lines
                    (cons (string-append
                           (plaintext:indent 1) "#   "
                           (gnc-commodity-get-mnemonic (car rest)) " "
                           (plaintext:amount-of figure report-commodity))
                          lines)))))))

;; What the book's foreign currency has gained or lost against what it cost,
;; read from the cost bases alone: each one's remaining balance valued at the
;; report's own closing rate, less what that balance cost. The account holding
;; the money says nothing here — a balance is money, and only a cost basis
;; knows what it was bought for.
(define (plaintext:revaluation price-fn side accounts moment report-commodity)
  (let ((table (gnc-commodity-table-get-table (gnc-get-current-book))))
    (let loop ((bases plaintext:cost-bases) (total 0))
      (if (null? bases)
          total
          (let* ((basis (car bases))
                 (commodity (gnc-commodity-table-lookup
                             table "CURRENCY" (plaintext:basis-mnemonic basis)))
                 ;; A price of nothing where the book holds none, as in the
                 ;; working that explains this key — the two must agree, and
                 ;; both must agree across the builds.
                 (price (and commodity (or (price-fn commodity) 0))))
            (loop (cdr bases)
                  (if (and price
                           (string=? (plaintext:basis-side basis) side)
                           (plaintext:basis-matches-holdings?
                            basis accounts moment table))
                      ;; Each basis's own gain, at the report currency's
                      ;; smallest unit, before it is added to the others — the
                      ;; same rule the three `_fx` keys follow, one level down.
                      ;; Taken from `plaintext:basis-gain`, which is what
                      ;; `plaintext:basis-working` prints as well, so the key
                      ;; and the line it is said to add up to are one
                      ;; computation rather than two that agree by luck.
                      (+ total (plaintext:basis-gain
                                basis (plaintext:exact price) report-commodity))
                      total)))))))

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
  (list "# Every account line is the balance GnuCash's own Balance Sheet or"
        "# Income Statement report gives it. An account line states what that"
        "# account itself holds — a parent's line is its own balance, not its"
        "# children's. A section's total, and any amount no account holds, is"
        "# a key."
        "#"
        "# share_price: and value: under an account line are what the report"
        "# valued that holding at on this date: the price read from the book's"
        "# price database, and what GnuCash converted the holding to. They are"
        "# not the keys of the same name on a transaction split, which record"
        "# the rate a transaction actually happened at and multiply out exactly."
        "# A price here changes with the date and with the book's prices; a"
        "# split's does not change at all."))

;; What the gain keys mean. The balance sheet's alone: the income statement
;; states none of them, and a page that explained keys it does not carry sent a
;; reader looking for figures that are not there — worse, it called
;; `gnucash_balancing_amount` "the last key" on a page whose last key is
;; `net_income`, and said of it "Nothing adds it in", which is untrue of that
;; one. Q-043 says these lines are added only where they mean something.
(define plaintext:gain-notes
  (list "#"
        "# Every section total on this page is the total GnuCash's own report"
        "# gives, but two. total_equity and total_liabilities_and_equity carry"
        "# the unrealized gain measured from the book's own cost bases, where"
        "# GnuCash's own page carries the amount it calculates to balance"
        "# itself, so the two totals differ by whatever those two amounts"
        "# differ by. gnucash_balancing_amount states GnuCash's beside them."
        "#"
        "# The gain keys are the exception. A gain on what the book still"
        "# holds is what it is worth at the price nearest this date, less what"
        "# it cost, and the two are added into the total."
        "#"
        "# For foreign currency that cost comes from the book's own cost"
        "# bases, the ones fx-balances reports. Everything else keeps"
        "# GnuCash's own revaluation: a security, and any currency whose cost"
        "# basis balance is not what the book owns — currency was spent there"
        "# without saying which cost basis it came out of, so what is left of"
        "# that balance stands for money the book no longer has, and is not"
        "# priced here."
        "#"
        "# A gain already taken is stated apart from one the book has yet to"
        "# take. What was taken left with the currency that earned it, and is"
        "# in the income and expense accounts already, so it is stated here"
        "# and added into nothing — counting it again would leave equity"
        "# standing against money that is gone. Only a gain on what the book"
        "# still holds reaches the equity total."
        "#"
        "# The gain keys end with GnuCash's own amount, printed as GnuCash"
        "# gives it. It is not a gain: it is an amount GnuCash calculates just"
        "# to balance the book, stated only so that a reader with GnuCash's own"
        "# page beside them can find the same number. Nothing adds it in."))

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
               ;; `plaintext:set-cost-bases!` before the report runs.
               ;;
               ;; The two keys divide by what the money is, never by who
               ;; measured it: a currency that is not the book's own is `_fx`,
               ;; and a security is `_other`. Within `_fx` the book's own cost
               ;; bases are preferred, and a currency they cannot speak for
               ;; keeps GnuCash's own revaluation — GnuCash's own report
               ;; chooser leaves the list empty, a borrowing opens a cost basis
               ;; on neither side, and a disposal that gives no cost basis guid
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
               (gnucash-revaluation
                (lambda (accounts)
                  (- (plaintext:converted
                      (plaintext:balance-as-of accounts moment)
                      report-commodity exchange-fn)
                     (plaintext:converted
                      (gnc:accounts-get-comm-total-assets
                       accounts
                       (lambda (account)
                         (gnc:account-get-comm-value-at-date account moment #f)))
                      report-commodity exchange-fn))))
               ;; The same figure commodity by commodity, each at the report
               ;; currency's smallest unit, which is how
               ;; `plaintext:gnucash-workings` prints them — so the lines under
               ;; a key add up to the key exactly.
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
                              (+ total (plaintext:as-money
                                        (gnucash-revaluation
                                         (plaintext:holding accounts (car rest)))
                                        report-commodity)))))))
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
                           side accounts moment report-commodity)
                          (gnucash-revaluation-by-commodity
                           (plaintext:fallback-accounts
                            side accounts moment report-commodity)))
                       report-commodity))))
               (unrealized-assets-fx (side-fx "asset" asset-accounts))
               (unrealized-liabilities-fx (side-fx "liability" liability-accounts))
               (unrealized-fx (+ unrealized-assets-fx unrealized-liabilities-fx))
               ;; A security is counted in units and priced rather than
               ;; converted from a currency, so it opens no cost basis however
               ;; its account is typed, and keeps GnuCash's own revaluation.
               ;;
               ;; An account held in the book's own currency takes no part in
               ;; either key. Reading GnuCash's reconstruction for one charged
               ;; a Canadian account 19.86 that was neither a gain nor a loss:
               ;; its splits sat in US dollar transactions, so their values
               ;; summed to nothing and the whole balance read as a movement.
               ;;
               ;; Commodity by commodity, as `plaintext:gnucash-workings`
               ;; prints them beneath it and as GnuCash itself converts: a
               ;; holding's whole quantity goes through the price once, which
               ;; is the figure `total_assets` carries. Account by account the
               ;; remainders are rounded away separately — one share worth
               ;; 10.005 in each of two brokerages came to 0.00 twice where
               ;; GnuCash converted the pair to 20.01 — and the sheet stopped
               ;; balancing on a book holding no foreign currency at all.
               (unrealized-other
                (if use-trading-accounts?
                    0
                    (gnucash-revaluation-by-commodity
                     (plaintext:securities holdings))))
               (total-unrealized (+ unrealized-fx unrealized-other))
               ;; The amount GnuCash calculates just to balance the book,
               ;; carried across as GnuCash gives it so a reader can find the
               ;; same number on GnuCash's own page. Never added into anything.
               (gnucash-balancing-amount
                (if use-trading-accounts?
                    0
                    (let ((gains (plaintext:collector)))
                      (gains 'merge asset-balance #f)
                      (gains 'minusmerge liability-balance #f)
                      (gains 'minusmerge
                             (gnc:accounts-get-comm-total-assets
                              (append asset-accounts liability-accounts)
                              (lambda (account)
                                (gnc:account-get-comm-value-at-date account moment #f)))
                             #f)
                      (plaintext:as-money
                       (plaintext:exact
                        (gnc:gnc-monetary-amount
                         (gnc:sum-collector-commodity gains report-commodity
                                                      exchange-fn)))
                       report-commodity))))
               ;; The equity total carries the gains the book measures for
               ;; itself, never GnuCash's balancing amount.
               ;;
               ;; GnuCash's amount is what is left when the summed split
               ;; values are taken from the converted balances, so putting it
               ;; here would make the sheet balance on every book by
               ;; construction — and balance on a figure this report exists to
               ;; correct. A split's value is stated in its transaction's
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
                   total-unrealized))
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
                                  (list line))))
               ;; How the gain figures were worked out, as comment lines.
               ;;
               ;; A reader can check an account line against their own book and
               ;; a section total by adding the lines above it. A gain is
               ;; measured against costs that are on no line of the page, so
               ;; without its working it is the one figure here that has to be
               ;; taken on trust. Both computations are shown: what the book's
               ;; own cost bases give, and what GnuCash's own revaluation gives
               ;; commodity by commodity, so the two can be read against each
               ;; other.
               ;;
               ;; Bound this late because it reads `price-fn` and
               ;; `gnucash-revaluation`, which are bound above it.
               (gain-workings
                (lambda ()
                  (if (or use-trading-accounts? (not plaintext:itemize?))
                      '()
                      (append
                       (list (string-append (plaintext:indent 1) "#")
                             (string-append
                              (plaintext:indent 1)
                              "# How each gain above was worked out. Every")
                             (string-append
                              (plaintext:indent 1)
                              "# gain list below adds up to the key it is under")
                             (string-append
                              (plaintext:indent 1)
                              "# — GnuCash's own amount is the exception, listed")
                             (string-append
                              (plaintext:indent 1)
                              "# commodity by commodity as GnuCash computes them")
                             (string-append
                              (plaintext:indent 1)
                              "# and not rounded to make the lines total it. A line")
                             (string-append
                              (plaintext:indent 1)
                              "# reading `cost ... at ... worth ...` is measured")
                             (string-append
                              (plaintext:indent 1)
                              "# from the book's own cost bases; a line of a")
                             (string-append
                              (plaintext:indent 1)
                              "# commodity and an amount is GnuCash's own")
                             (string-append
                              (plaintext:indent 1)
                              "# revaluation of everything the book holds of it —")
                             (string-append
                              (plaintext:indent 1)
                              "# what that is worth at the price nearest this date,")
                             (string-append
                              (plaintext:indent 1)
                              "# less the sum of its splits' values. By commodity")
                             (string-append
                              (plaintext:indent 1)
                              "# and not by account, because that is how GnuCash")
                             (string-append
                              (plaintext:indent 1)
                              "# converts a holding: once, whole."))
                       ;; Left off with the key itself: a page that itemised a
                       ;; key it does not state would leave a reader looking
                       ;; for a figure that is not there.
                       (if plaintext:realized-known?
                           (plaintext:key-workings
                            "realized_gains_fx"
                            (plaintext:realized-workings report-commodity))
                           '())
                       (plaintext:key-workings
                        "unrealized_gains_assets_fx"
                        (append (plaintext:cost-basis-workings
                                 "asset" asset-accounts moment price-fn report-commodity)
                                (plaintext:gnucash-workings
                                 (plaintext:fallback-accounts
                                  "asset" asset-accounts moment report-commodity)
                                 report-commodity gnucash-revaluation)))
                       (plaintext:key-workings
                        "unrealized_gains_liabilities_fx"
                        (append (plaintext:cost-basis-workings
                                 "liability" liability-accounts moment price-fn
                                 report-commodity)
                                (plaintext:gnucash-workings
                                 (plaintext:fallback-accounts
                                  "liability" liability-accounts moment report-commodity)
                                 report-commodity gnucash-revaluation)))
                       (plaintext:key-workings
                        "unrealized_gains_other"
                        (plaintext:gnucash-workings
                         (plaintext:securities holdings) report-commodity
                         gnucash-revaluation))
                       ;; The one working that is not a decomposition of its
                       ;; key. Every other figure here is rounded per term and
                       ;; then added, so the lines come to the key exactly. This
                       ;; key is GnuCash's own amount, carried across so a
                       ;; reader can find the same number on GnuCash's page —
                       ;; and GnuCash converts the whole holding at once, so two
                       ;; accounts in one foreign currency have their split
                       ;; values added before the conversion rounds them. Listed
                       ;; per account the lines can come to a cent less. Rounding
                       ;; the key to match them would make it agree with the
                       ;; lines and stop agreeing with GnuCash, which is the only
                       ;; reason the key exists, so the lines stay as they are
                       ;; and the page above says they are not a total.
                       (plaintext:key-workings
                        "gnucash_balancing_amount"
                        (plaintext:gnucash-workings
                         holdings report-commodity gnucash-revaluation)))))))
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
          ;; The gain paragraphs go on a page that has gain keys. A book using
          ;; trading accounts keeps those gains in its Trading accounts and
          ;; states `trading_gains` instead, printing none of the gain keys and
          ;; no `gnucash_balancing_amount` — so the paragraphs would explain
          ;; figures that are not there, and would tell a reader that two of
          ;; its totals differ from GnuCash's when neither does: measured on
          ;; such a book, 3,550.00 of liabilities and 34,982.80 of equity come
          ;; to the 38,532.80 it states, with no unrealized total in it. That
          ;; is the same fault as putting them on an income statement, one page
          ;; along.
          (plaintext:page-explaining
           (if use-trading-accounts?
               plaintext:notes
               (append plaintext:notes plaintext:gain-notes))
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
                 (if plaintext:realized-known?
                     (list (string-append
                            (plaintext:indent 1) "realized_gains_fx: "
                            (plaintext:amount-of realized-fx report-commodity))
                           (string-append
                            (plaintext:indent 1) "total_realized_gains: "
                            (plaintext:amount-of realized-fx report-commodity)))
                     '())
                 (list (string-append
                        (plaintext:indent 1) "unrealized_gains_assets_fx: "
                        (plaintext:amount-of unrealized-assets-fx report-commodity))
                       (string-append
                        (plaintext:indent 1) "unrealized_gains_liabilities_fx: "
                        (plaintext:amount-of unrealized-liabilities-fx report-commodity))
                       (string-append
                        (plaintext:indent 1) "unrealized_gains_fx: "
                        (plaintext:amount-of unrealized-fx report-commodity))
                       (string-append
                        (plaintext:indent 1) "unrealized_gains_other: "
                        (plaintext:amount-of unrealized-other report-commodity))
                       (string-append
                        (plaintext:indent 1) "total_unrealized_gains: "
                        (plaintext:amount-of total-unrealized report-commodity))
                       (string-append
                        (plaintext:indent 1) "gnucash_balancing_amount: "
                        (plaintext:amount-of gnucash-balancing-amount report-commodity)))))
            (gain-workings)
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
