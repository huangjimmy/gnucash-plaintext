;; A report of one's own that puts `class="company-table"` on a paragraph.
;;
;; The renderer hands back its page as a string, which GnuCash prints as it
;; is, so the markup is exactly what is written here: the seller's details in
;; a `<p>` carrying the class, and no `<div>` anywhere on the page.
;;
;; The reader kept the class README says the registration numbers go in, so
;; they have every reason to think the GST number is printed. There is no
;; `<div>` block and no table to put it in, so it is not, and the run says so.

(define (a-report-whose-company-class-is-on-a-paragraph-renderer report-obj)
  (string-append
    "<html><body>"
    "<p class=\"company-table\">MY COMPANY, IN A PARAGRAPH</p>"
    "</body></html>"))

(gnc:define-report
  'version 1
  'name "A Report Whose Company Class Is On A Paragraph"
  'report-guid "b1b2b1b2b1b2b1b2b1b2b1b2b1b2b1b2"
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
  'renderer a-report-whose-company-class-is-on-a-paragraph-renderer)
