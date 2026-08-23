;; A report of one's own that declares no `General / Invoice Number` option.
;;
;; That option is how an invoice reaches a report — this tool sets it to the
;; guid of the invoice or bill being printed — so a report without it cannot
;; be told which one to draw. GnuCash ships several such reports (a
;; Balance Sheet, a Transaction Report); they are not registered on a run of
;; this tool, which loads only the invoice modules, but a `.scm` of the
;; reader's own is loaded by `--report-file` and can be anything, and
;; forgetting that one option is a plausible first attempt.
;;
;; What it used to cost: the write is the one option that is not optional, so
;; it is not wrapped in the tolerant `try-set`, and GnuCash's own error came
;; out as it stood — `(misc-error (#f ~A (Attempt to write non-existent
;; option …)))` on 4.x and 5.x, and a bare `wrong-type-arg` out of
;; `vector-ref` on 3.8. Every other first-attempt mistake in this area earns a
;; sentence, and this one now does too.

(define (a-report-that-takes-no-invoice-renderer report-obj)
  (let ((page (gnc:make-html-document)))
    (gnc:html-document-set-title! page "A Report That Takes No Invoice")
    (gnc:html-document-add-object!
      page
      (gnc:make-html-text
        (gnc:html-markup-p "THIS REPORT DRAWS NO INVOICE")))
    page))

(gnc:define-report
  'version 1
  'name "A Report That Takes No Invoice"
  'report-guid "d0c0d0c0d0c0d0c0d0c0d0c0d0c0d0c0"
  'options-generator
    (lambda ()
      ;; Deliberately bare: no invoice option, nothing to say which one.
      (if (defined? 'gnc-new-optiondb)
          (gnc-new-optiondb)
          (gnc:new-options)))
  'renderer a-report-that-takes-no-invoice-renderer)
