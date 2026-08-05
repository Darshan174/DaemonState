import { Link } from "react-router-dom";

import DaemonStateIcon from "../components/DaemonStateIcon";
import "./LandingReplica.css";
import "./PermissionsTerms.css";


const GITHUB_REPOSITORY = "https://github.com/Darshan174/DaemonState";
const LICENSING_GUIDE = `${GITHUB_REPOSITORY}/blob/main/docs/licensing.md`;
const MIT_BOUNDARY = `${GITHUB_REPOSITORY}/commit/45b7a6e653a1762bf91b99fae4c7adf3dafc55ce`;


export default function PermissionsTerms() {
  return (
    <div className="dsr-landing dsr-terms">
      <header className="dsr-terms-header">
        <Link to="/" aria-label="DaemonState home" className="dsr-brand">
          <DaemonStateIcon size={29} />
          <span>DaemonState</span>
        </Link>
        <nav aria-label="Legal navigation" className="dsr-terms-header-nav">
          <Link to="/privacy">Privacy</Link>
          <Link to="/#early-access">Return to early access</Link>
        </nav>
      </header>

      <main>
        <div className="dsr-terms-layout">
          <div className="dsr-terms-hero">
            <p className="dsr-terms-kicker">
              <span aria-hidden="true" />
              DO / DON&apos;T AGREEMENT
            </p>
            <h1 aria-label="Permissions & terms">
              Permissions
              <span>&amp; terms</span>
            </h1>
            <p className="dsr-terms-version">DAEMONSTATE 0.3.0+ / SUL-1.0</p>
            <div className="dsr-terms-actions">
              <a href="/assets/legal/LICENSE" className="dsr-terms-primary">
                Read the license
              </a>
              <a
                href={LICENSING_GUIDE}
                target="_blank"
                rel="noreferrer"
                className="dsr-terms-secondary"
              >
                GitHub guide <span aria-hidden="true">↗</span>
              </a>
            </div>
          </div>

          <article>
            <header className="dsr-terms-intro">
              <p>
                DaemonState 0.3.0 and later are source-available under the
                Sustainable Use License 1.0. By using the software, you agree
                to that license.
              </p>
              <aside>
                This page is a plain-language guide. The published
                {" "}<a href="/assets/legal/LICENSE">license text</a> controls if
                anything here differs from it.
              </aside>
            </header>

            <section>
              <p className="dsr-terms-section-label">PERMITTED</p>
              <h2>What you may do</h2>
              <ul>
                <li>Use DaemonState for personal or noncommercial purposes.</li>
                <li>
                  Use and modify your company&apos;s own self-hosted installation
                  for its internal business.
                </li>
                <li>
                  Study, audit, copy, and adapt the source for those permitted
                  uses.
                </li>
                <li>
                  Share original or modified copies free of charge for
                  noncommercial purposes, while keeping the required terms and
                  notices with them.
                </li>
              </ul>
            </section>

            <section>
              <p className="dsr-terms-section-label is-restricted">NOT INCLUDED</p>
              <h2>Commercial uses need permission</h2>
              <p>The standard license does not let you:</p>
              <ul>
                <li>Sell DaemonState copies or paid distributions.</li>
                <li>White-label DaemonState as a commercial product.</li>
                <li>
                  Operate it as a paid hosted or managed service for other
                  people.
                </li>
                <li>
                  Sell access to its functionality or make DaemonState a
                  substantial source of value in a paid customer offering.
                </li>
              </ul>
              <p>
                A different commercial use requires separate written permission
                from every copyright holder whose work is included.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">CONDITIONS</p>
              <h2>Keep the notices with the work</h2>
              <ul>
                <li>
                  Anyone receiving a copy must also receive the license terms.
                </li>
                <li>
                  Do not remove or obscure license, copyright, or other licensor
                  notices.
                </li>
                <li>
                  Mark modified copies with a prominent notice that you changed
                  the software.
                </li>
                <li>
                  No trademark or other rights are granted unless the license
                  says so.
                </li>
              </ul>
            </section>

            <section>
              <p className="dsr-terms-section-label">PATENTS / TERMINATION</p>
              <h2>Permission depends on compliance</h2>
              <p>
                The patent grant follows the same license limits and ends if you
                or your company make a written patent claim covered by the
                license. Use outside the terms is unlicensed and automatically
                terminates your license.
              </p>
              <p>
                After notice of a first violation, stopping every violation
                within 30 days reinstates the license retroactively. A later
                violation after reinstatement terminates it permanently.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">NO WARRANTY</p>
              <h2>Provided as is</h2>
              <p>
                As far as the law allows, DaemonState comes without warranty or
                condition, and its licensors are not liable for damages arising
                from these terms or from the use or nature of the software.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">VERSION HISTORY</p>
              <h2>Earlier releases stay MIT-licensed</h2>
              <p>
                Versions through 0.2.0 were released under the MIT License. That
                grant is not retroactively changed. The final MIT-licensed source
                is commit
                {" "}<a href={MIT_BOUNDARY} target="_blank" rel="noreferrer">
                  45b7a6e
                </a>.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">OTHER COMPONENTS</p>
              <h2>Third-party terms still apply</h2>
              <p>
                Third-party software and fonts keep their own licenses and are
                not covered by DaemonState&apos;s SUL-1.0 grant. Review the
                {" "}<a href="/assets/legal/THIRD_PARTY_NOTICES.txt">
                  third-party notices
                </a> before redistributing the product.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">PRIVACY / QUESTIONS</p>
              <h2>Need clarity or a different permission?</h2>
              <p>
                Waitlist data is handled under the <Link to="/privacy">privacy
                notice</Link>. For a commercial exception or a use near the
                license boundary, get legal advice or written permission instead
                of relying on this summary.
              </p>
              <a
                href="https://github.com/Darshan174"
                target="_blank"
                rel="noreferrer"
                className="dsr-terms-contact"
              >
                Contact the repository owner <span aria-hidden="true">↗</span>
              </a>
            </section>
          </article>
        </div>
      </main>

      <footer className="dsr-terms-footer">
        <span>© 2026 DaemonState</span>
        <div>
          <Link to="/privacy">Privacy notice</Link>
          <a href={GITHUB_REPOSITORY} target="_blank" rel="noreferrer">GitHub</a>
        </div>
      </footer>
    </div>
  );
}
