;; Two reports of one's own that answer to a single name.
;;
;; The fixture behind the ambiguity refusal: after loading this, two
;; registered templates are named "A Name Two Reports Answer To", so
;; `--report "A Name Two Reports Answer To"` resolves two ways and
;; `gnc:report-templates-for-each`, which walks a hash, would hand back
;; whichever came first.
;;
;; **Why two of mine rather than one of mine named after one of GnuCash's.**
;; The situation this is drawn from is real — someone replacing the Fancy
;; Invoice page keeps its name — and taking that name here would exercise the
;; same code, because the lookup only counts how many templates matched. But
;; a report registers into a process-global registry that nothing resets, and
;; the suite renders `--report "Fancy Invoice"` in several other tests: once
;; this file had been loaded, every one of those would refuse for ambiguity,
;; and which tests those are would depend on pytest's collection order. That
;; is a trap for whoever adds the next Fancy Invoice test, so the collision is
;; kept between two reports that exist only here.

(define (an-ambiguous-report-renderer which)
  (lambda (report-obj)
    (let* ((page (gnc:make-html-document))
           (options (gnc:report-options report-obj))
           (invoice (gnc:option-value
                      (gnc:lookup-option options "General" "Invoice Number"))))
      (gnc:html-document-set-title! page "A Name Two Reports Answer To")
      (gnc:html-document-add-object!
        page
        (gnc:make-html-text
          (gnc:html-markup-p
            (string-append "A REPORT NAMED LIKE ANOTHER: " which))
          (gnc:html-markup-p
            (string-append "invoice: "
                           (if (and invoice (not (null? invoice)))
                               (gncInvoiceGetID invoice)
                               "none")))))
      page)))

;; The options generator both share. Declared both ways GnuCash has had, for
;; the reason `a_report_of_your_own.scm` explains.
(define (an-ambiguous-report-options)
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

(gnc:define-report
  'version 1
  'name "A Name Two Reports Answer To"
  'report-guid "fa9cefa9cefa9cefa9cefa9cefa9ce01"
  'options-generator an-ambiguous-report-options
  'renderer (an-ambiguous-report-renderer "the first"))

(gnc:define-report
  'version 1
  'name "A Name Two Reports Answer To"
  'report-guid "fa9cefa9cefa9cefa9cefa9cefa9ce02"
  'options-generator an-ambiguous-report-options
  'renderer (an-ambiguous-report-renderer "the second"))
