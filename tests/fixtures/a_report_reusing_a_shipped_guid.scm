;; A report of one's own that keeps the guid it was copied from.
;;
;; README says to start from GnuCash's `invoice.scm`, and that file carries
;; `'report-guid "5123a759ceb9483abf2182d01c140e8d"` — the Printable Invoice's
;; — so copying it and changing the layout without minting a new guid is one
;; keystroke away. This fixture is that mistake.
;;
;; **GnuCash refuses it**, rather than letting the copy take the original's
;; place. `gnc:define-report` checks the registry and logs "One of your
;; reports has a report-guid that is a duplicate. Please check the report
;; system, especially your saved reports, for a report with this report-guid:
;; …", leaving what was there untouched. Measured on 5.10 and 3.8: after
;; loading this, the template under that guid is byte for byte the one
;; `invoice.scm` registered, the registry is the same size, and this report is
;; simply absent.
;;
;; So the page that draws is GnuCash's own, and everything that follows from
;; that — its display options set, its heading checked, the seller's block
;; required — is right. What this pins is that the tool agrees with GnuCash
;; about whose report it is, rather than treating a guid named on the command
;; line as evidence.

(define (a-report-reusing-a-shipped-guid-renderer report-obj)
  (let ((document (gnc:make-html-document)))
    (gnc:html-document-set-title! document "Not The Printable Invoice")
    (gnc:html-document-add-object!
      document
      (gnc:make-html-text
        (gnc:html-markup-p "THIS SHOULD NEVER DRAW")))
    document))

(gnc:define-report
  'version 1
  'name "Not The Printable Invoice"
  'report-guid "5123a759ceb9483abf2182d01c140e8d"
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
  'renderer a-report-reusing-a-shipped-guid-renderer)
