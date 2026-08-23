;; A report of one's own whose guid is a shipped one in capitals.
;;
;; The registry compares guids with `equal?`, so `5123A759…` is not
;; `5123a759…` — GnuCash does not see a duplicate and this registers as a
;; *second* entry beside the Printable Invoice.
;;
;; Which makes `--report 5123a759ceb9483abf2182d01c140e8d` ambiguous. A guid
;; is hex, where case means nothing, so the lookup matches without regard to
;; it — and there are now two templates it matches. Kept to whichever the hash
;; yielded first, the same command would draw this page or GnuCash's, the
;; registration numbers spliced in or not, the heading check enforced or not,
;; with nothing on the page saying which it was. So it is refused, and the
;; refusal names both entries, exactly as it does for a name two reports
;; answer to.
;;
;; **This one does leak**, unlike `two_reports_of_one_name.scm`, and cannot
;; avoid it: the collision *is* with a shipped guid, so there is no way to
;; stage it between two reports of its own. Once loaded, the entry stays for
;; the life of the process and `--report 5123a759…` is ambiguous for every
;; test after it. What that does not touch is anything the suite actually
;; does: printing with no `--report` interpolates the guid straight into
;; `gnc:make-report-options` without walking the registry, and `--report
;; "Printable Invoice"` matches by name, which this report does not share.
;; A test naming the Printable Invoice *by guid* would have to load this
;; file too, or run before it.

(define (a-report-in-caps-renderer report-obj)
  (let ((page (gnc:make-html-document)))
    (gnc:html-document-set-title! page "A Report In Caps")
    (gnc:html-document-add-object!
      page
      (gnc:make-html-text (gnc:html-markup-p "A REPORT WHOSE GUID IS CAPS")))
    page))

(define (a-report-in-caps-options)
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
  'name "A Report In Caps"
  'report-guid "5123A759CEB9483ABF2182D01C140E8D"
  'options-generator a-report-in-caps-options
  'renderer a-report-in-caps-renderer)

;; A second report in the same file, colliding with nothing.
;;
;; One `.scm` holding several reports is ordinary, and it is what makes the
;; difference between naming the guid that collided and naming everything the
;; file registered. Listed wholesale, the refusal sends the reader to look at
;; reports that have nothing to do with the ambiguity — and puts a list of
;; unbounded length ahead of the matched ids, which are the part the message's
;; length limit was widened to keep.
(gnc:define-report
  'version 1
  'name "A Report In Caps That Collides With Nothing"
  'report-guid "5b1e5b1e5b1e5b1e5b1e5b1e5b1e5b1e"
  'options-generator a-report-in-caps-options
  'renderer a-report-in-caps-renderer)
