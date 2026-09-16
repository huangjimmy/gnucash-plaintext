;; A report of one's own whose `company-table` block is never closed.
;;
;; The renderer hands back its page as a string, which GnuCash prints as it
;; is, so nothing closes the `<div>` for it. `gnc:html-markup/attr/no-end`,
;; which 3.4 and 5.10 both ship, writes the same shape.
;;
;; A block with no end has no inside to put a row in: the table after the
;; opening tag could as well be the line items. So the GST number is not
;; printed, and because the reader kept the class, the run says so.

(define (a-report-whose-company-block-never-closes-renderer report-obj)
  (string-append
    "<html><body>"
    "<div class=\"company-table\">"
    "<table><tbody><tr><td>MY COMPANY, IN A BLOCK THAT NEVER CLOSES</td></tr>"
    "</tbody></table>"
    "</body></html>"))

(gnc:define-report
  'version 1
  'name "A Report Whose Company Block Never Closes"
  'report-guid "c2c3c2c3c2c3c2c3c2c3c2c3c2c3c2c3"
  'options-generator
    (lambda ()
      (if (defined? 'gnc-new-optiondb)
          (let ((options (gnc-new-optiondb)))
            (gnc-register-invoice-option options
                                         "General" "Invoice Number" "x" "" '())
            options)
          (let ((options (gnc:new-options)))
            (gnc:register-option
              options
              (gnc:make-invoice-option "General" "Invoice Number" "x" ""
                                       (lambda () '()) #f))
            options)))
  'renderer a-report-whose-company-block-never-closes-renderer)
