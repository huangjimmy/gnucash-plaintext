;; A GnuCash report of one's own, written the way GnuCash's own are.
;;
;; This is the fixture behind `--report-file`: a `.scm` that calls
;; `gnc:define-report`, which is exactly how the Printable Invoice and every
;; other report GnuCash ships gets into the registry. Once loaded it is
;; indistinguishable from them, so `--report "A Report Of Your Own"` finds it.
;;
;; Deliberately not a copy of an invoice report — it prints one unmistakable
;; sentence and the invoice's id — because what the test is asking is "did
;; *my* report draw this page", and a page that looks like GnuCash's cannot
;; answer that.
;;
;; It declares its options both ways GnuCash has had, because the supported
;; builds span both and a fixture that worked on one half would be testing the
;; seam on one half:
;;
;;   4.x/5.x  (gnc-new-optiondb) + (gnc-register-invoice-option db …)
;;   3.8      (gnc:new-options)  + (gnc:register-option (gnc:make-invoice-option …))
;;
;; A report of your own has to do the same if you want it to run on both; the
;; branch is `(defined? 'gnc-new-optiondb)`, asked of the build rather than
;; inferred from its version. GnuCash's own `invoice.scm` is the reference for
;; whichever one you are on.

(define (a-report-of-your-own-renderer report-obj)
  (let* ((page (gnc:make-html-document))
         (options (gnc:report-options report-obj))
         (invoice (gnc:option-value
                    (gnc:lookup-option options "General" "Invoice Number"))))
    (gnc:html-document-set-title! page "A Report Of Your Own")
    (gnc:html-document-add-object!
      page
      (gnc:make-html-text
        (gnc:html-markup-p
          "THIS PAGE WAS DRAWN BY A REPORT OF MY OWN")
        ;; An option of this report's own, under a name GnuCash's invoice
        ;; reports also use. The default below stands unless the *book*
        ;; carries a footer, set with `set-invoice-style`: a sentence the
        ;; reader wrote goes on whatever report draws the page. The three
        ;; display switches are the opposite — set by `print-invoice` and
        ;; `print-bill` on GnuCash's own invoice reports alone, never on a
        ;; report loaded with `--report-file`.
        (gnc:html-markup-p
          (string-append
            "extra notes: "
            (gnc:option-value
              (gnc:lookup-option options "Display" "Extra Notes"))))
        (gnc:html-markup-p
          (string-append "invoice: "
                         (if (and invoice (not (null? invoice)))
                             (gncInvoiceGetID invoice)
                             "none")))))
    page))

;; The guid is written in upper case on purpose. `uuidgen` on macOS prints
;; upper case, so a `.scm` naturally says `'report-guid "B0DC…"` — and the
;; registry is a hash compared with `equal?`, so a lookup that lowercases what
;; the reader typed would refuse this report while GnuCash's own, which
;; register lower case, would refuse the upper-case spelling of theirs. Both
;; are tried; this fixture is the half that would otherwise go untested.
(gnc:define-report
  'version 1
  'name "A Report Of Your Own"
  'report-guid "B0DCB0DCB0DCB0DCB0DCB0DCB0DCB0DC"
  'options-generator
    (lambda ()
      (if (defined? 'gnc-new-optiondb)
          ;; 4.x / 5.x
          (let ((options (gnc-new-optiondb)))
            (gnc-register-invoice-option options
                                         "General" "Invoice Number" "x" "" '())
            (gnc-register-text-option options
                                      "Display" "Extra Notes" "y" ""
                                      "MY OWN EXTRA NOTES")
            options)
          ;; 3.8
          (let ((options (gnc:new-options)))
            (gnc:register-option
              options
              (gnc:make-invoice-option "General" "Invoice Number" "x" ""
                                       (lambda () '()) #f))
            (gnc:register-option
              options
              (gnc:make-text-option "Display" "Extra Notes" "y" ""
                                    "MY OWN EXTRA NOTES"))
            options)))
  'renderer a-report-of-your-own-renderer)
