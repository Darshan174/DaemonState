import { Link } from "react-router-dom";

import DaemonStateIcon from "../components/DaemonStateIcon";
import "./LandingReplica.css";
import "./PermissionsTerms.css";


const PUBLIC_GITHUB_REPOSITORY = "https://github.com/Darshan174/DaemonState";


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
              SHIPPED SOFTWARE TERMS
            </p>
            <h1 aria-label="Permissions & terms">
              Permissions
              <span>&amp; terms</span>
            </h1>
            <p className="dsr-terms-version">
              CURRENT DISTRIBUTION / SUL-1.0
            </p>
            <div className="dsr-terms-actions">
              <a
                href="/assets/legal/LICENSE"
                className="dsr-terms-primary"
              >
                Read current license
              </a>
              <a
                href={PUBLIC_GITHUB_REPOSITORY}
                target="_blank"
                rel="noreferrer"
                className="dsr-terms-secondary"
              >
                View public toolkit <span aria-hidden="true">↗</span>
              </a>
            </div>
          </div>

          <article>
            <header className="dsr-terms-intro">
              <p>
                DaemonState software distributed with the current SUL-1.0
                LICENSE—including the packaged product built from this
                repository—is source-available under that license.
              </p>
              <aside>
                This page is a plain-language guide. The <a href="/assets/legal/LICENSE">
                  license
                </a> and NOTICE shipped with a distribution control that
                distribution. Separate product or commercial terms control only
                when they are expressly provided for a particular offering or
                use.
              </aside>
            </header>

            <section>
              <p className="dsr-terms-section-label">LICENSING MAP</p>
              <h2>The terms follow what you receive</h2>
              <ul>
                <li>
                  The current packaged DaemonState product built from this
                  repository is distributed under SUL-1.0.
                </li>
                <li>
                  The public integration and demonstration toolkit on GitHub is
                  separately distributed under SUL-1.0.
                </li>
                <li>
                  Hosted services, private components not distributed under
                  SUL-1.0, and separately licensed commercial offerings are
                  governed by their applicable written terms.
                </li>
                <li>
                  A separate commercial license changes the standard grant only
                  for the party and use that written license covers.
                </li>
              </ul>
            </section>

            <section>
              <p className="dsr-terms-section-label">SUL-1.0 DISTRIBUTIONS</p>
              <h2>What SUL-1.0 permits</h2>
              <p>
                For DaemonState software distributed under SUL-1.0, including
                the current packaged product and public toolkit, the license
                permits personal and noncommercial use and a company&apos;s internal
                business use. It also permits you to:
              </p>
              <ul>
                <li>
                  Study, audit, copy, and adapt the software for those permitted
                  uses.
                </li>
                <li>
                  Share original or modified copies free of charge for
                  noncommercial purposes while keeping the required terms and
                  notices with them.
                </li>
              </ul>
            </section>

            <section>
              <p className="dsr-terms-section-label is-restricted">NOT INCLUDED</p>
              <h2>Commercial uses need permission</h2>
              <p>The standard SUL-1.0 license does not let you:</p>
              <ul>
                <li>Sell copies or paid distributions.</li>
                <li>White-label the software as a commercial product.</li>
                <li>Operate it as a paid hosted or managed service for others.</li>
                <li>
                  Sell access to its functionality or make the software a
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
              <h2>Keep the notices with the software</h2>
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
              <h2>SUL permission depends on compliance</h2>
              <p>
                The patent grant follows the same SUL limits and ends if you or
                your company make a written patent claim covered by the license.
                Use outside the terms is unlicensed and automatically terminates
                the SUL license.
              </p>
              <p>
                After notice of a first violation, stopping every violation
                within 30 days reinstates the license retroactively. A later
                violation after reinstatement terminates it permanently.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">NO WARRANTY</p>
              <h2>SUL-licensed software is provided as is</h2>
              <p>
                As far as the law allows, SUL-licensed software comes without
                warranty or condition, and its licensors are not liable for
                damages arising from the SUL terms or from the use or nature of
                the software. Any separately licensed product or service warranty
                is governed by its own applicable terms.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">HISTORICAL RELEASES</p>
              <h2>Earlier license grants are preserved</h2>
              <p>
                Certain historical software published by the project, including
                code released under the MIT License, remains governed by the
                license that accompanied those copies. Those grants are not
                retroactively revoked, but they do not apply to current or future
                DaemonState software unless expressly stated.
              </p>
            </section>

            <section>
              <p className="dsr-terms-section-label">OTHER COMPONENTS</p>
              <h2>Third-party terms still apply</h2>
              <p>
                Third-party software and fonts keep their own licenses. They are
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
                notice</Link>. For separate product terms, a commercial exception,
                or a use near the SUL boundary, get legal advice or written
                permission instead of relying on this summary.
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
          <a href={PUBLIC_GITHUB_REPOSITORY} target="_blank" rel="noreferrer">GitHub</a>
        </div>
      </footer>
    </div>
  );
}
