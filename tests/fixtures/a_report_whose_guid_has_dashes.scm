;; A report of one's own that registered the guid `uuidgen` printed.
;;
;; `uuidgen` prints `7cd07cd0-7cd0-7cd0-7cd0-7cd07cd07cd0`, and a reader
;; writing their first `.scm` pastes that into `'report-guid` as it came. The
;; registry keeps it exactly — dashes as much as case — so the id this report
;; answers to has dashes in it.
;;
;; Which makes the naming work on both sides or on neither. Stripping only
;; what the reader types at the command line compares a bare 32 characters
;; against a dashed key and fails; leaving both alone fails the other way
;; round, for anyone who typed the undashed form. Either refusal arrives as
;; "no report of that name is registered on this build", with advice about
;; translated names, for a string that is plainly a guid.
;;
;; So both sides have their dashes taken out before they are compared, and
;; this report is reachable by `--report` written either way.

(define (a-report-with-a-dashed-guid-renderer report-obj)
  (let* ((page (gnc:make-html-document))
         (options (gnc:report-options report-obj))
         (invoice (gnc:option-value
                    (gnc:lookup-option options "General" "Invoice Number"))))
    (gnc:html-document-set-title! page "A Report With A Dashed Guid")
    (gnc:html-document-add-object!
      page
      (gnc:make-html-text
        (gnc:html-markup-p "A REPORT WHOSE GUID CAME FROM UUIDGEN")
        (gnc:html-markup-p
          (string-append "invoice: "
                         (if (and invoice (not (null? invoice)))
                             (gncInvoiceGetID invoice)
                             "none")))))
    page))

(gnc:define-report
  'version 1
  'name "A Report With A Dashed Guid"
  'report-guid "7cd07cd0-7cd0-7cd0-7cd0-7cd07cd07cd0"
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
  'renderer a-report-with-a-dashed-guid-renderer)
