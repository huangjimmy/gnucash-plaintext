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

(define (plaintext:company-name)
  (let ((name (gnc:company-info (gnc-get-current-book) gnc:*company-name*)))
    (if (string? name) name "")))

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

;; A line of the page: its label, a balance in the account's own commodity
;; (or ""), and a figure in the report's currency (or "").
(define (plaintext:line label balance figure)
  (list label balance figure))

(define (plaintext:heading label)
  (plaintext:line label "" ""))

(define plaintext:blank (plaintext:line "" "" ""))

(define (plaintext:money monetary)
  (gnc:monetary->string monetary))

;; `add-subtotal-line` in balance-sheet.scm and income-statement.scm.
(define (plaintext:total label negative-label collector report-commodity exchange-fn)
  (let* ((negative? (and negative-label
                         (negative?
                          (gnc:gnc-monetary-amount
                           (gnc:sum-collector-commodity
                            collector report-commodity exchange-fn)))))
         (shown (if negative?
                    (gnc:commodity-collector-get-negated collector)
                    collector)))
    (plaintext:line (if negative? negative-label label)
                    ""
                    (plaintext:money
                     (gnc:sum-collector-commodity shown report-commodity exchange-fn)))))

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
         (label (string-append (make-string (* 2 display-depth) #\space)
                               (if (eq? row-type 'subtotal-row) "Total " "")
                               (value 'account-name))))
    (cond
     ((or (not collector)
          (and (eq? (value 'zero-balance-display-mode) 'omit-balance)
               (gnc-commodity-collector-allzero? collector)))
      (list (plaintext:heading label)))
     (else
      (let ((signed (if (gnc-reverse-balance account)
                        (gnc:commodity-collector-get-negated collector)
                        collector)))
        (if (and (eq? (value 'multicommodity-mode) 'table)
                 (eq? row-type 'account-row)
                 (not (gnc:uniform-commodity? signed report-commodity)))
            ;; `gnc-commodity-table`: each commodity's balance beside its
            ;; value in the report's currency, one line each.
            (let loop ((balances (signed 'format gnc:make-gnc-monetary #f))
                       (shown-label label)
                       (lines '()))
              (if (null? balances)
                  (reverse lines)
                  (loop (cdr balances)
                        ""
                        (cons (plaintext:line
                               shown-label
                               (plaintext:money (car balances))
                               (plaintext:money
                                (exchange-fn (car balances) report-commodity)))
                              lines))))
            (list (plaintext:line
                   label ""
                   (plaintext:money
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

;; A section: its heading, its accounts, its total and a blank line.
(define (plaintext:section heading? heading account-lines total? total)
  (append (if heading? (list (plaintext:heading heading)) '())
          account-lines
          (if total? (list total) '())
          (list plaintext:blank)))

;; The page: the title, then each line with its label on the left and its
;; figures right-aligned in columns at least two spaces apart.
(define (plaintext:page title lines)
  (define (widest column)
    (apply max 0 (map (lambda (line) (string-length (list-ref line column))) lines)))
  (let ((label-width (widest 0))
        (balance-width (widest 1))
        (figure-width (widest 2)))
    (define (written line)
      (string-trim-right
       (string-append
        (string-pad-right (list-ref line 0) label-width)
        (if (zero? balance-width)
            ""
            (string-append "  " (string-pad (list-ref line 1) balance-width)))
        "  "
        (string-pad (list-ref line 2) figure-width))))
    (string-append title "\n\n" (string-join (map written lines) "\n") "\n")))

(define (plaintext:no-accounts title)
  (plaintext:page title
                  (list (plaintext:heading "No accounts selected")
                        (plaintext:heading
                         "This report requires accounts to be selected in the report options."))))

;; The options every account table is given, as GnuCash's renderers give them.
(define (plaintext:table-env option start end report-commodity exchange-fn)
  (let ((depth-limit (option "Accounts" "Levels of Subaccounts")))
    (list (list 'start-date start)
          (list 'end-date end)
          (list 'display-tree-depth (if (eq? depth-limit 'all)
                                        (gnc:get-current-account-tree-depth)
                                        depth-limit))
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

(define (plaintext:params option)
  (list (list 'parent-account-balance-mode (option "Display" "Parent account balances"))
        (list 'zero-balance-display-mode
              (if (option "Display" "Omit zero balance figures") 'omit-balance 'show-balance))
        (list 'multicommodity-mode
              (and (option "Commodities" "Show Foreign Currencies") 'table))
        (list 'rule-mode #f)))

;; balance-sheet.scm, `balance-sheet-renderer`.
(define (plaintext:balance-sheet-renderer report-obj)
  (define (option section name) (plaintext:option report-obj section name))
  (let* ((book (gnc-get-current-book))
         (moment (gnc:time64-end-day-time
                  (gnc:date-option-absolute-time
                   (option "General" "Balance Sheet Date"))))
         (accounts (option "Accounts" "Accounts"))
         (title (string-trim-both
                 (string-append (plaintext:company-name) " "
                                (option "General" "Report Title") " "
                                (qof-print-date moment)))))
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
               (params (plaintext:params option))
               (total (lambda (label negative-label collector)
                        (plaintext:total label negative-label collector
                                         report-commodity exchange-fn)))
               (unless-zero (lambda (collector line)
                              (if (gnc-commodity-collector-allzero? collector) '() (list line))))

               (liabilities
                (plaintext:section
                 (option "Display" "Label the liabilities section") "Liabilities"
                 (plaintext:account-lines table-env params liability-accounts)
                 (option "Display" "Include liabilities total")
                 (total "Total Liabilities" #f liability-balance)))
               (equity
                (append
                 (if (option "Display" "Label the equity section")
                     (list (plaintext:heading "Equity"))
                     '())
                 (plaintext:account-lines table-env params equity-accounts)
                 (unless-zero retained-earnings
                              (total "Retained Earnings" "Retained Losses" retained-earnings))
                 (unless-zero trading-balance
                              (total "Trading Gains" "Trading Losses" trading-balance))
                 (unless-zero unrealized-gains
                              (total "Unrealized Gains" "Unrealized Losses" unrealized-gains))
                 (if (option "Display" "Include equity total")
                     (list (total "Total Equity" #f total-equity))
                     '())
                 (list plaintext:blank))))
          (plaintext:page
           title
           (append
            (plaintext:section
             (option "Display" "Label the assets section") "Assets"
             (plaintext:account-lines table-env params asset-accounts)
             (option "Display" "Include assets total")
             (total "Total Assets" #f asset-balance))
            (if (option "General" "Use standard US layout")
                (append liabilities equity)
                (append equity liabilities))
            (list (total "Total Liabilities & Equity" #f liabilities-and-equity))))))))

;; income-statement.scm, `income-statement-renderer-internal`.
(define (plaintext:income-statement-renderer report-obj)
  (define (option section name) (plaintext:option report-obj section name))
  (let* ((start-printable (gnc:date-option-absolute-time (option "General" "Start Date")))
         (start (gnc:time64-start-day-time start-printable))
         (end (gnc:time64-end-day-time
               (gnc:date-option-absolute-time (option "General" "End Date"))))
         (accounts (option "Accounts" "Accounts"))
         (title (string-trim-both
                 (string-append (plaintext:company-name) " "
                                (option "General" "Report Title")
                                " For Period Covering " (qof-print-date start-printable)
                                " to " (qof-print-date end)))))
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
               (params (plaintext:params option))
               (total (lambda (label collector)
                        (plaintext:total label #f collector report-commodity exchange-fn)))

               (revenue
                (plaintext:section
                 (option "Display" "Label the revenue section") "Revenues"
                 (plaintext:account-lines table-env params revenue-accounts)
                 (option "Display" "Include revenue total")
                 (total "Total Revenue" revenue-total)))
               (trading
                (if (null? trading-accounts)
                    '()
                    (plaintext:section
                     (option "Display" "Label the trading accounts section") "Trading"
                     (plaintext:account-lines table-env params trading-accounts)
                     (option "Display" "Include trading accounts total")
                     (total "Total Trading" trading-total))))
               (expenses
                (plaintext:section
                 (option "Display" "Label the expense section") "Expenses"
                 (plaintext:account-lines table-env params expense-accounts)
                 (option "Display" "Include expense total")
                 (total "Total Expenses" expense-total)))

               ;; `add-report-line`
               (net (gnc:sum-collector-commodity net-income report-commodity exchange-fn))
               (loss? (negative? (gnc:gnc-monetary-amount net)))
               (net-line (plaintext:line
                          (if loss? "Net loss for Period" "Net income for Period")
                          ""
                          (plaintext:money (if loss? (gnc:monetary-neg net) net)))))
          (plaintext:page
           title
           (append
            (if (option "Display" "Display in standard, income first, order")
                (append revenue trading expenses)
                (append expenses trading revenue))
            (list net-line)))))))

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
