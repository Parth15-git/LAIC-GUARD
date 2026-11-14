from __future__ import annotations
import argparse, hashlib, json, shutil, math, os
from pathlib import Path
from collections import Counter
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
from shapely.geometry import box, LineString, MultiLineString, GeometryCollection
from shapely.ops import transform
import shapely

CATALOGUE_SHA = '0e20c3ef9268e728d320dcf55e18d66638aa92f66371af2915a34760f9837315'
PILOT_REGIONS = [
    {'region_id':'HIMALAYA_TIBET','west':60.0,'east':105.0,'south':20.0,'north':42.0},
    {'region_id':'JAPAN_KURIL','west':125.0,'east':180.0,'south':30.0,'north':60.0},
    {'region_id':'SUNDA_INDONESIA','west':90.0,'east':145.0,'south':-15.0,'north':25.0},
    {'region_id':'ANDES','west':-85.0,'east':-55.0,'south':-60.0,'north':15.0},
]
ASSIGN_COLORS = {
    'HIMALAYA_TIBET_CORE':'#8c564b',
    'JAPAN_KURIL':'#1f77b4',
    'SUNDA_INDONESIA_CORE':'#2ca02c',
    'ANDES':'#ff7f0e',
    'OVERLAP_REVIEW_HIMALAYA_SUNDA':'#d62728',
    'OUTSIDE_PILOT':'#9e9e9e',
}
BOUNDARY_COLORS = {
    'subduction zone':'#c0392b',
    'collision zone':'#e67e22',
    'dextral transform':'#6c3483',
    'sinistral transform':'#8e44ad',
    'spreading center':'#2471a3',
    'extension zone':'#17a589',
    'inferred':'#7f8c8d',
}


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def norm_str(v):
    if pd.isna(v): return ''
    return str(v).strip()


def row_flag_specs(row):
    ass=norm_str(row['pilot_assignment_v001'])
    fam=norm_str(row['candidate_domain_family_v001'])
    sub=norm_str(row['candidate_subdomain_v001'])
    orogen=norm_str(row['PB2002_OROGEN_NAME'])
    hsub=norm_str(row['Hasterok_subplate'])
    btype=norm_str(row['nearest_boundary_type'])
    bname=norm_str(row['nearest_boundary_name'])
    specs=[]
    def add(code, group, severity, source_field, source_value, reason):
        specs.append((code,group,severity,source_field,source_value,reason))
    if ass=='OVERLAP_REVIEW_HIMALAYA_SUNDA':
        add('MYANMAR_RECTANGLE_OVERLAP','PILOT_GEOMETRY_CONFLICT','HIGH','pilot_assignment_v001',ass,
            'Event falls in the exact intersection of the two exploratory boxes; retain separate pending tectonic-domain decision.')
    if orogen=='Persia-Tibet-Burma' and ass=='OUTSIDE_PILOT':
        add('PERSIA_TIBET_BURMA_OROGEN_OUTSIDE_PILOT','OROGEN_EXTENT_VS_PILOT_BOX','HIGH','PB2002_OROGEN_NAME',orogen,
            'PB2002 orogen membership lies outside all four exploratory rectangles; do not truncate the complex orogen at the pilot-box edge.')
    if orogen=='Persia-Tibet-Burma' and ass=='SUNDA_INDONESIA_CORE':
        add('PERSIA_TIBET_BURMA_OROGEN_IN_SUNDA_BOX','OROGEN_EXTENT_VS_PILOT_BOX','HIGH','PB2002_OROGEN_NAME',orogen,
            'PB2002 Persia-Tibet-Burma membership occurs inside the Sunda rectangle; geometric inclusion is not a tectonic-domain decision.')
    if hsub=='Bering Sea':
        add('BERING_SEA_SUBPLATE','ADJACENT_DOMAIN','HIGH','Hasterok_subplate',hsub,
            'Bering Sea source subplate crosses the old Japan-Kuril rectangle edge; maintain as a distinct adjacent review domain.')
    if orogen=='Alaska-Yukon':
        add('ALASKA_YUKON_OROGEN','OROGEN_EDGE_CASE','MEDIUM','PB2002_OROGEN_NAME',orogen,
            'PB2002 Alaska-Yukon orogen membership is outside the original four pilot boxes.')
    if orogen=='western Aleutians':
        add('WESTERN_ALEUTIANS_OROGEN','OROGEN_EDGE_CASE','HIGH','PB2002_OROGEN_NAME',orogen,
            'PB2002 western Aleutians orogen intersects events included by the old Japan-Kuril rectangle; review as an Aleutian arc segment.')
    if hsub=='Ryukyu':
        add('RYUKYU_SUBPLATE','ADJACENT_DOMAIN','HIGH','Hasterok_subplate',hsub,
            'Ryukyu subplate events are split across multiple pilot-box assignments and outside-pilot space.')
    if orogen=='Philippines':
        add('PHILIPPINES_PB2002_OROGEN','COMPLEX_OROGEN','HIGH','PB2002_OROGEN_NAME',orogen,
            'PB2002 Philippines orogen lies inside the broad Sunda rectangle; PB2002 explicitly treats this as a complex orogen, not a simple rigid-plate unit.')
    if fam=='PHILIPPINE_MOBILE_BELT_REVIEW':
        add('PHILIPPINE_MOBILE_BELT_CANDIDATE','ADJACENT_COMPLEX_DOMAIN','HIGH','candidate_domain_family_v001',fam,
            'Provisional Hasterok-subplate grouping spans Philippine candidate units; review separately from Sunda/Indonesia.')
    if fam=='NEW_GUINEA_EASTERN_INDONESIA_REVIEW':
        add('NEW_GUINEA_EASTERN_INDONESIA_CANDIDATE','ADJACENT_DOMAIN','MEDIUM','candidate_domain_family_v001',fam,
            'Candidate domain includes New Guinea and eastern Indonesia subplates, some outside the Sunda rectangle.')
    if fam=='MARIANA_ARC_REVIEW':
        add('MARIANA_ARC_CANDIDATE','ADJACENT_DOMAIN','MEDIUM','candidate_domain_family_v001',fam,
            'Mariana arc candidate is split between the Sunda rectangle and outside-pilot area; do not merge with Sunda.')
    if ass=='SUNDA_INDONESIA_CORE' and fam!='SUNDA_ARC_SEGMENTATION_REVIEW':
        add('SUNDA_BOX_NON_SUNDA_ARC_CANDIDATE','PILOT_BOX_MIXED_TECTONIC_UNITS','HIGH','candidate_domain_family_v001',fam or 'UNASSIGNED',
            'Event is inside the broad Sunda rectangle but does not carry the provisional Sunda arc segmentation tag.')
    if ass=='JAPAN_KURIL' and fam!='KURIL_KAMCHATKA_ARC_REVIEW':
        add('JAPAN_KURIL_BOX_NON_KURIL_CANDIDATE','PILOT_BOX_MIXED_TECTONIC_UNITS','HIGH','candidate_domain_family_v001',fam or 'UNASSIGNED',
            'Event is inside the Japan-Kuril rectangle but is not tagged as Kuril-Kamchatka arc candidate.')
    if ass=='ANDES' and fam in {'CENTRAL_AMERICA_CARIBBEAN_REVIEW','SOUTH_AMERICAN_PLATE_REVIEW','NAZCA_PLATE_REVIEW','COCOS_PLATE_REVIEW','SCOTIA_DOMAIN_REVIEW'}:
        add('ANDES_BOX_NON_ANDES_REVIEW','PILOT_BOX_MIXED_TECTONIC_UNITS','HIGH','candidate_domain_family_v001',fam,
            'Event is inside the old Andes rectangle but its provisional source-unit tag is Central America/Caribbean, broad South American plate, Nazca, Cocos or Scotia; review before defining an Andes population.')
    if ass=='HIMALAYA_TIBET_CORE' and fam!='INDIA_EURASIA_COLLISION_BELT_REVIEW':
        add('HIMALAYA_BOX_ADJACENT_OR_UNTAGGED','PILOT_BOX_MIXED_TECTONIC_UNITS','MEDIUM','candidate_domain_family_v001',fam or 'UNASSIGNED',
            'Event is inside the Himalaya-Tibet rectangle but does not carry the primary India-Eurasia collision-belt candidate family.')
    if ass=='OUTSIDE_PILOT' and fam:
        add('OUTSIDE_PILOT_WITH_CANDIDATE_DOMAIN','ADJACENT_DOMAIN','MEDIUM','candidate_domain_family_v001',fam,
            'Event is outside all four pilot rectangles but belongs to a provisional candidate domain; outside-pilot is not a tectonically inactive/control designation.')
    if not fam:
        add('UNASSIGNED_REQUIRES_REVIEW','UNASSIGNED','MEDIUM','candidate_domain_family_v001','',
            'No provisional Hasterok subplate candidate family was registered; retain the event and review the available source layers rather than exclude it.')
    if btype=='inferred':
        add('NEAREST_BOUNDARY_INFERRED','BOUNDARY_SOURCE_QUALIFIER','LOW','nearest_boundary_type',btype,
            'Nearest mapped boundary record is classified as inferred; retain separately from named/established boundary interpretations.')
    if not bname:
        add('NEAREST_BOUNDARY_NAME_MISSING','BOUNDARY_SOURCE_QUALIFIER','LOW','nearest_boundary_name','',
            'Nearest source boundary record has no feature name; type and plate-pair fields may still be populated.')
    if pd.isna(row.get('Hasterok_plate')) or norm_str(row.get('Hasterok_plate'))=='':
        add('HASTEROK_PLATE_POLYGON_NO_MATCH','POLYGON_OVERLAY_QUALIFIER','MEDIUM','Hasterok_plate','',
            'No Hasterok plate polygon name was carried into the overlay; inspect location and polygon coverage, including the antimeridian.')
    return specs


def add_flag_columns(df):
    all_specs=[]
    per_event=[]
    for _,r in df.iterrows():
        specs=row_flag_specs(r)
        all_specs.extend((r,s) for s in specs)
        per_event.append(specs)
    df=df.copy()
    df['gis_review_flags_v001']=[';'.join(s[0] for s in x) for x in per_event]
    df['gis_review_flag_count_v001']=[len(x) for x in per_event]
    df['gis_review_required_v001']=[bool(x) for x in per_event]
    return df, all_specs


def geom_transform_lon360(geom):
    def f(x,y,z=None):
        xx=np.asarray(x)
        yy=np.asarray(y)
        xout=np.where(xx<0,xx+360,xx)
        return (xout,yy) if z is None else (xout,yy,z)
    return transform(f,geom)


def geom_parts_for_plot(geom):
    if geom is None or geom.is_empty: return []
    if isinstance(geom, LineString): return [geom]
    if isinstance(geom, MultiLineString): return list(geom.geoms)
    if isinstance(geom, GeometryCollection):
        out=[]
        for g in geom.geoms: out.extend(geom_parts_for_plot(g))
        return out
    return []


def line_segments_no_dateline(geom):
    out=[]
    for line in geom_parts_for_plot(geom):
        coords=list(line.coords)
        seg=[]
        for xy in coords:
            if seg and abs(xy[0]-seg[-1][0])>180:
                if len(seg)>1: out.append(seg)
                seg=[xy]
            else:
                seg.append(xy)
        if len(seg)>1: out.append(seg)
    return out


def _filtered_clipped_geometries(gdf, extent, wrap360=False):
    xmin,ymin,xmax,ymax=extent
    geoms=np.asarray(gdf.geometry.array,dtype=object).copy()
    invalid=~shapely.is_valid(geoms)
    if invalid.any():
        geoms[invalid]=shapely.make_valid(geoms[invalid])
    if wrap360:
        def xy_transform(coords):
            out=np.array(coords,copy=True)
            out[:,0]=np.where(out[:,0]<0,out[:,0]+360,out[:,0])
            return out
        geoms=shapely.transform(geoms,xy_transform)
        invalid_wrap=~shapely.is_valid(geoms)
        if invalid_wrap.any():
            geoms[invalid_wrap]=shapely.make_valid(geoms[invalid_wrap])
    bounds=shapely.bounds(geoms)
    mask=(bounds[:,0]<=xmax)&(bounds[:,2]>=xmin)&(bounds[:,1]<=ymax)&(bounds[:,3]>=ymin)
    geoms=geoms[mask]
    clipped=shapely.intersection(geoms,box(xmin,ymin,xmax,ymax))
    good=~shapely.is_empty(clipped)
    return clipped[good], np.where(mask)[0][good]


def plot_lines(ax, lines, extent, wrap360=False, lw=0.65, alpha=0.7):
    for typ,color in BOUNDARY_COLORS.items():
        sub=lines[lines['type'].fillna('').astype(str).eq(typ)]
        if sub.empty: continue
        geoms, _ = _filtered_clipped_geometries(sub,extent,wrap360=wrap360)
        if len(geoms):
            gpd.GeoSeries(geoms,crs='EPSG:4326').plot(ax=ax,color=color,linewidth=lw,alpha=alpha,zorder=1)


def draw_polygon_layer(ax, gdf, extent, wrap360=False, edgecolor='#aab7b8', lw=0.35, alpha=0.35, linestyle='-'):
    geoms,_=_filtered_clipped_geometries(gdf,extent,wrap360=wrap360)
    if len(geoms):
        polys=gpd.GeoSeries(geoms,crs='EPSG:4326')
        polys.boundary.plot(ax=ax,color=edgecolor,linewidth=lw,alpha=alpha,linestyle=linestyle,zorder=0)


def draw_boxes(ax, extent, wrap360=False):
    for b in PILOT_REGIONS:
        west,east=b['west'],b['east']
        if wrap360 and west<0: west+=360
        if wrap360 and east<0: east+=360
        if west>180 and east<=180: east+=360
        rect=Rectangle((west,b['south']),east-west,b['north']-b['south'],fill=False,
                       edgecolor='#1f1f1f',linewidth=1.0,linestyle='--',alpha=.8,zorder=4)
        ax.add_patch(rect)


def prep_event_lons(df, wrap360):
    x=df['longitude_deg'].to_numpy(dtype=float)
    if wrap360: x=np.where(x<0,x+360,x)
    return x


def regional_map(cross, plates, provinces, pbplates, orogens, boundaries, out_png, out_pdf):
    panels=[
        ('Himalaya–Tibet–Burma', (55,3,112,48), False),
        ('Japan–Ryukyu–Kuril', (118,18,164,64), False),
        ('Aleutian–Bering (0–360° longitude)', (155,43,215,72), True),
        ('Sunda–Philippines–Molucca–New Guinea', (88,-17,156,32), False),
        ('Andes and adjacent Central America/Caribbean', (-100,-62,-43,22), False),
        ('South Pacific adjacent systems', (155,-32,215,12), True),
    ]
    fig,axs=plt.subplots(3,2,figsize=(19,19),constrained_layout=True)
    axs=axs.ravel()
    for ax,(title,ext,wrap) in zip(axs,panels):
        xmin,ymin,xmax,ymax=ext
        # Filter source geometries by bbox in native coordinates; for wrap panels retain all geometry records.
        pl=plates; pr=provinces; pp=pbplates; og=orogens; bd=boundaries
        draw_polygon_layer(ax,pl,ext,wrap360=wrap,edgecolor='#7f8c8d',lw=.38,alpha=.40)
        draw_polygon_layer(ax,pr,ext,wrap360=wrap,edgecolor='#a3c6c4',lw=.28,alpha=.26,linestyle=':')
        draw_polygon_layer(ax,pp,ext,wrap360=wrap,edgecolor='#2874a6',lw=.48,alpha=.45,linestyle='-.')
        draw_polygon_layer(ax,og,ext,wrap360=wrap,edgecolor='#c0392b',lw=.85,alpha=.85,linestyle='--')
        plot_lines(ax,bd,ext,wrap360=wrap,lw=.72,alpha=.72)
        x=prep_event_lons(cross,wrap)
        y=cross['latitude_deg'].to_numpy(float)
        inside=(x>=xmin)&(x<=xmax)&(y>=ymin)&(y<=ymax)
        sub=cross.loc[inside]
        xx=x[inside]; yy=y[inside]
        for ass,color in ASSIGN_COLORS.items():
            mask=sub['pilot_assignment_v001'].fillna('').eq(ass).to_numpy()
            if mask.any():
                ax.scatter(xx[mask],yy[mask],s=16 if ass!='OUTSIDE_PILOT' else 10,
                           c=color,edgecolors='white' if ass!='OUTSIDE_PILOT' else 'none',
                           linewidths=.25,alpha=.88 if ass!='OUTSIDE_PILOT' else .55,zorder=3)
        # Ring events that have one of the main domain-conflict flags.
        conflict_codes=['MYANMAR_RECTANGLE_OVERLAP','PERSIA_TIBET_BURMA_OROGEN_OUTSIDE_PILOT','BERING_SEA_SUBPLATE',
                        'RYUKYU_SUBPLATE','PHILIPPINES_PB2002_OROGEN','SUNDA_BOX_NON_SUNDA_ARC_CANDIDATE',
                        'JAPAN_KURIL_BOX_NON_KURIL_CANDIDATE','ANDES_BOX_NON_ANDES_REVIEW']
        edge=sub['gis_review_flags_v001'].fillna('').apply(lambda s:any(code in s.split(';') for code in conflict_codes)).to_numpy()
        if edge.any():
            ax.scatter(xx[edge],yy[edge],s=34,facecolors='none',edgecolors='#111111',linewidths=.8,zorder=5)
        draw_boxes(ax,ext,wrap360=wrap)
        ax.set_xlim(xmin,xmax); ax.set_ylim(ymin,ymax)
        ax.set_title(f'{title}\n{len(sub)} catalogue events in view',fontsize=10,weight='bold')
        ax.set_xlabel('Longitude (°E)' if wrap else 'Longitude (°)')
        ax.set_ylabel('Latitude (°)')
        ax.grid(True,linewidth=.35,alpha=.35)
        ax.set_facecolor('#f7f9f9')
    legend=[]
    for a,c in ASSIGN_COLORS.items():
        legend.append(Line2D([0],[0],marker='o',color='none',markerfacecolor=c,markeredgecolor='white',markersize=6,label=a.replace('_',' ')))
    legend += [
      Line2D([0],[0],marker='o',color='none',markerfacecolor='none',markeredgecolor='#111111',markersize=7,label='Flagged edge-case event'),
      Line2D([0],[0],color='#c0392b',lw=1.0,ls='--',label='PB2002 orogen boundary'),
      Line2D([0],[0],color='#7f8c8d',lw=1.0,label='Hasterok plate/subplate outline'),
      Line2D([0],[0],color='#a3c6c4',lw=1.0,ls=':',label='Hasterok geological province outline'),
      Line2D([0],[0],color='#2874a6',lw=1.0,ls='-.',label='PB2002 plate outline'),
    ]
    for label,color in BOUNDARY_COLORS.items():
        legend.append(Line2D([0],[0],color=color,lw=1.2,label=f'Boundary: {label}'))
    fig.legend(handles=legend,loc='lower center',ncol=6,fontsize=7.3,frameon=True,bbox_to_anchor=(.5,-.015))
    fig.suptitle('LAIC-GUARD Stage 1C.2.5 — GIS regional review\nOriginal pilot boxes and tectonic source layers; event colours retain v001 assignment',fontsize=15,weight='bold')
    fig.savefig(out_png,dpi=220,bbox_inches='tight')
    fig.savefig(out_pdf,bbox_inches='tight')
    plt.close(fig)


def global_map(cross, boundaries, out_png, out_pdf):
    fig,ax=plt.subplots(figsize=(18,9),constrained_layout=True)
    # Boundary linework; avoid false lines that bridge the antimeridian.
    for _,r in boundaries.iterrows():
        typ=norm_str(r.get('type')); color=BOUNDARY_COLORS.get(typ,'#7f8c8d')
        for seg in line_segments_no_dateline(r.geometry):
            xs=[p[0] for p in seg]; ys=[p[1] for p in seg]
            ax.plot(xs,ys,color=color,lw=.36,alpha=.42,zorder=1)
    for ass,color in ASSIGN_COLORS.items():
        d=cross[cross.pilot_assignment_v001.fillna('').eq(ass)]
        ax.scatter(d.longitude_deg,d.latitude_deg,s=8 if ass=='OUTSIDE_PILOT' else 14,c=color,
                   edgecolors='none' if ass=='OUTSIDE_PILOT' else 'white',linewidths=.25,
                   alpha=.48 if ass=='OUTSIDE_PILOT' else .9,label=f'{ass.replace("_"," ")} (n={len(d)})',zorder=3)
    for b in PILOT_REGIONS:
        ax.add_patch(Rectangle((b['west'],b['south']),b['east']-b['west'],b['north']-b['south'],
                               fill=False,edgecolor='#111111',linewidth=1.2,linestyle='--',zorder=4))
        ax.text((b['west']+b['east'])/2,(b['south']+b['north'])/2,b['region_id'].replace('_',' '),
                fontsize=7,ha='center',va='center',color='#111111',bbox=dict(facecolor='white',alpha=.65,edgecolor='none',pad=1),zorder=5)
    ax.set_xlim(-180,180);ax.set_ylim(-62,78);ax.set_xlabel('Longitude (°)');ax.set_ylabel('Latitude (°)')
    ax.set_title('Global catalogue overview — all 1,186 events and original exploratory rectangles',fontsize=14,weight='bold')
    ax.grid(True,linewidth=.45,alpha=.35);ax.set_facecolor('#f7f9f9')
    ax.legend(loc='lower center',bbox_to_anchor=(.5,-.20),ncol=3,fontsize=8,frameon=True)
    fig.savefig(out_png,dpi=220,bbox_inches='tight');fig.savefig(out_pdf,bbox_inches='tight');plt.close(fig)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-dir',required=True)
    ap.add_argument('--source-dir',required=True)
    ap.add_argument('--output-dir',required=True)
    args=ap.parse_args()
    inp=Path(args.input_dir); src=Path(args.source_dir); out=Path(args.output_dir)
    if out.exists(): raise SystemExit(f'Output already exists: {out}')
    (out/'analysis').mkdir(parents=True);(out/'maps').mkdir();(out/'inputs').mkdir();(out/'scripts').mkdir()
    cat=inp/'event_catalogue_v002.csv'
    crosspath=inp/'event_level_candidate_segmentation_review_v001.csv'
    overlay=inp/'event_level_tectonic_overlay_v001.csv'
    dist=inp/'event_level_tectonic_boundary_distances_v001.csv'
    if sha256(cat)!=CATALOGUE_SHA: raise SystemExit('Frozen catalogue SHA-256 mismatch')
    c=pd.read_csv(cat); x=pd.read_csv(crosspath)
    if len(c)!=1186 or c.event_id.nunique()!=1186: raise SystemExit('Catalogue count/ID check failed')
    if len(x)!=1186 or x.event_id.nunique()!=1186: raise SystemExit('Crosswalk count/ID check failed')
    if set(c.event_id)!=set(x.event_id): raise SystemExit('Catalogue/crosswalk event-ID sets differ')
    # Confirm proposal source fields reconcile with original catalogue.
    merged=c[['event_id','origin_time_utc','latitude_deg','longitude_deg','depth_km','magnitude','magnitude_type','place']].merge(
        x[['event_id','origin_time_utc','latitude_deg','longitude_deg','depth_km','magnitude','magnitude_type','place']],
        on='event_id',suffixes=('_cat','_cross'),validate='one_to_one')
    mismatch=[]
    for col in ['origin_time_utc','latitude_deg','longitude_deg','depth_km','magnitude','magnitude_type','place']:
        a=merged[f'{col}_cat'].fillna('').astype(str); b=merged[f'{col}_cross'].fillna('').astype(str)
        if not a.equals(b): mismatch.append(col)
    if mismatch: raise SystemExit('Crosswalk source-field mismatch: '+','.join(mismatch))
    # Read source layers.
    plates=gpd.read_file(src/'Hasterok'/'plates.shp')
    provinces=gpd.read_file(src/'Hasterok'/'global_gprv.shp')
    boundaries=gpd.read_file(src/'Hasterok'/'plate_boundaries.shp')
    pbplates=gpd.read_file(src/'PB2002_plates.geojson')
    orogens=gpd.read_file(src/'PB2002_orogens.geojson')
    # Keep all catalogue records, and generate event-level flag ledger.
    review, all_specs=add_flag_columns(x)
    review.to_csv(out/'analysis'/'event_level_gis_review_v001.csv',index=False)
    event_lookup=review.set_index('event_id')
    flag_rows=[]
    for r,s in all_specs:
        code,group,severity,field,value,reason=s
        flag_rows.append({
            'event_id':r['event_id'],'flag_code':code,'flag_group':group,'severity':severity,
            'source_field':field,'source_value':value,'pilot_assignment_v001':r['pilot_assignment_v001'],
            'candidate_domain_family_v001':r['candidate_domain_family_v001'],
            'candidate_subdomain_v001':r['candidate_subdomain_v001'],
            'PB2002_OROGEN_NAME':r['PB2002_OROGEN_NAME'],'Hasterok_subplate':r['Hasterok_subplate'],
            'nearest_boundary_type':r['nearest_boundary_type'],'nearest_boundary_distance_km':r['nearest_boundary_distance_km'],
            'review_reason':reason
        })
    flags=pd.DataFrame(flag_rows)
    flags.to_csv(out/'analysis'/'edge_case_ledger_v001.csv',index=False)
    summary=flags.groupby(['flag_code','flag_group','severity'],dropna=False).agg(
        event_count=('event_id','nunique'),ledger_rows=('event_id','size')).reset_index().sort_values(['severity','event_count'],ascending=[True,False])
    # stable custom severity order
    sev_order={'HIGH':0,'MEDIUM':1,'LOW':2}
    summary['_o']=summary.severity.map(sev_order)
    summary.sort_values(['_o','event_count','flag_code'],ascending=[True,False,True]).drop(columns='_o').to_csv(out/'analysis'/'edge_case_flag_summary_v001.csv',index=False)
    # Candidate rectangle cross-membership table from source overlay.
    ov=pd.read_csv(overlay)
    comp=[]
    for rid,boxd in [(b['region_id'],b) for b in PILOT_REGIONS]:
        inside=review.pilot_assignment_v001.eq(rid if rid!='HIMALAYA_TIBET' else 'HIMALAYA_TIBET_CORE')
        # assignment may reserve overlap events separately; use overlay's raw box bit for inclusive membership.
        colmap={'HIMALAYA_TIBET':'in_himalaya_tibet_box','JAPAN_KURIL':'in_japan_kuril_box','SUNDA_INDONESIA':'in_sunda_indonesia_box','ANDES':'in_andes_box'}
        d=ov[ov[colmap[rid]].astype(bool)].merge(review[['event_id','candidate_domain_family_v001','candidate_subdomain_v001','Hasterok_subplate','PB2002_OROGEN_NAME']],on='event_id',validate='one_to_one')
        vc=d.candidate_domain_family_v001.fillna('UNASSIGNED').value_counts()
        for fam,n in vc.items():
            comp.append({'pilot_box':rid,'candidate_domain_family_v001':fam,'event_count':int(n),'box_membership_total':len(d)})
    pd.DataFrame(comp).to_csv(out/'analysis'/'pilot_box_candidate_family_composition_v001.csv',index=False)
    # Selected event register for the user-promised case topics.
    wanted_codes={'MYANMAR_RECTANGLE_OVERLAP','PERSIA_TIBET_BURMA_OROGEN_OUTSIDE_PILOT','BERING_SEA_SUBPLATE',
                  'WESTERN_ALEUTIANS_OROGEN','RYUKYU_SUBPLATE','PHILIPPINES_PB2002_OROGEN',
                  'PHILIPPINE_MOBILE_BELT_CANDIDATE','NEW_GUINEA_EASTERN_INDONESIA_CANDIDATE','MARIANA_ARC_CANDIDATE',
                  'ANDES_BOX_NON_ANDES_REVIEW','SUNDA_BOX_NON_SUNDA_ARC_CANDIDATE','JAPAN_KURIL_BOX_NON_KURIL_CANDIDATE'}
    selected=flags[flags.flag_code.isin(wanted_codes)].merge(
        review[['event_id','origin_time_utc','year_utc','latitude_deg','longitude_deg','depth_km','magnitude','magnitude_type','place']],
        on='event_id',how='left',validate='many_to_one')
    selected.to_csv(out/'analysis'/'priority_edge_case_register_v001.csv',index=False)
    # QA summary
    flag_counts={r.flag_code:int(r.event_count) for r in summary.itertuples()}
    qa={
      'stage':'1C.2.5','status':'GIS_REVIEW_PACKAGE_GENERATED_NOT_REGION_APPROVAL',
      'catalogue_sha256':sha256(cat),'catalogue_rows':len(c),'catalogue_unique_event_ids':int(c.event_id.nunique()),
      'crosswalk_rows':len(x),'crosswalk_unique_event_ids':int(x.event_id.nunique()),'catalogue_crosswalk_field_mismatches':mismatch,
      'event_level_review_rows':len(review),'event_level_review_unique_ids':int(review.event_id.nunique()),
      'events_with_any_flag':int(review.gis_review_required_v001.sum()),'long_form_flag_rows':len(flags),
      'unique_event_ids_in_priority_edge_register':int(selected.event_id.nunique()),
      'source_features':{'Hasterok_plate_polygons':len(plates),'Hasterok_geological_provinces':len(provinces),'Hasterok_boundary_records':len(boundaries),'PB2002_plate_features':len(pbplates),'PB2002_orogen_features':len(orogens)},
      'flag_event_counts':flag_counts,
      'original_overlap_events_preserved':int(review.pilot_assignment_v001.eq('OVERLAP_REVIEW_HIMALAYA_SUNDA').sum()),
      'outside_pilot_events_preserved':int(review.pilot_assignment_v001.eq('OUTSIDE_PILOT').sum()),
      'supporting_event_records_downloaded':0,'sequence_labels_assigned':False,'final_regions_frozen':False,
      'limitations':['One invalid Hasterok Antarctic plate polygon was repaired in memory with shapely.make_valid for clipping/rendering only; original source file remains unchanged.', 'Overlay depicts source polygons and lines at their supplied present-day geometry; not a time-dependent tectonic reconstruction.',
        'Point-in-polygon source tags and nearest-boundary distances are review evidence, not rupture/fault causation or final study-region membership.',
        'PB2002 orogens, Hasterok plates/subplates and geological provinces are separate layers; they are not mutually exclusive.',
        'Old rectangles are drawn only as exploratory pilot windows, not tectonic boundaries.',
        'Global overview linework omits line segments that would falsely bridge the antimeridian; the Bering panel uses 0–360 longitude.']
    }
    with open(out/'QA_SUMMARY.json','w') as f: json.dump(qa,f,indent=2)
    # Maps
    global_map(review,boundaries,out/'maps'/'global_catalogue_overview_v001.png',out/'maps'/'global_catalogue_overview_v001.pdf')
    regional_map(review,plates,provinces,pbplates,orogens,boundaries,out/'maps'/'regional_gis_review_v001.png',out/'maps'/'regional_gis_review_v001.pdf')
    # copy exact analysis inputs
    shutil.copy2(cat,out/'inputs'/'event_catalogue_v002.csv')
    shutil.copy2(crosspath,out/'inputs'/'event_level_candidate_segmentation_review_v001.csv')
    shutil.copy2(overlay,out/'inputs'/'event_level_tectonic_overlay_v001.csv')
    shutil.copy2(dist,out/'inputs'/'event_level_tectonic_boundary_distances_v001.csv')
    # copy source layers (with sidecars)
    (out/'inputs'/'tectonic_sources'/'Hasterok').mkdir(parents=True)
    for f in (src/'Hasterok').glob('*'):
        if f.suffix.lower() in {'.shp','.shx','.dbf','.prj','.cpg'}:
            shutil.copy2(f,out/'inputs'/'tectonic_sources'/'Hasterok'/f.name)
    for f in src.glob('PB2002_*.geojson'):
        shutil.copy2(f,out/'inputs'/'tectonic_sources'/f.name)
    commitfile=src/'HASTEROK_COMMIT.txt'
    if commitfile.exists(): shutil.copy2(commitfile,out/'inputs'/'tectonic_sources'/'HASTEROK_COMMIT.txt')
    # Copy script into package.
    shutil.copy2(Path(__file__),out/'scripts'/'build_stage1c2_gis_review_v001.py')
    # source notes
    notes=f'''# Stage 1C.2.5 GIS review — source and method notes\n\n## Inputs\n- Frozen USGS target catalogue v002; SHA-256 `{CATALOGUE_SHA}`.\n- Stage 1C.2.4 provisional candidate crosswalk v001.\n- Stage 1C.2 tectonic overlay v001.\n- Stage 1C.2.3 boundary-distance audit v001.\n- Hasterok et al. (2022) global plates/subplates, geological provinces and plate-boundary linework, source revision `{(commitfile.read_text().strip() if commitfile.exists() else 'not supplied')}`.\n- Bird (2003) PB2002 plates and orogens GeoJSON layers.\n\n## Map interpretation\nEvent colours show the **original Stage 1C.2 pilot assignment**, not a new tectonic classification. Black-ringed points have one or more priority edge-case flags. Gray source polygon outlines are Hasterok plate/subplate polygons; pale dotted outlines are geological provinces; blue dash-dot outlines are PB2002 plate polygons; red dashed outlines are PB2002 orogens; line colours distinguish the Hasterok boundary `type` attribute. Dashed black rectangles are the original exploratory pilot boxes.\n\n## Edge-case rules\nThe ledger is generated by explicit field-value and assignment rules in the included script. It preserves one row per event-flag, so an event may appear more than once in `edge_case_ledger_v001.csv`. `event_level_gis_review_v001.csv` is the one-row-per-event master table with a semicolon-delimited flag list. These flags are review prompts—not automatic reassignment or exclusions.\n\n## Important limitations\n1. One invalid Hasterok Antarctic plate polygon was repaired in memory with `shapely.make_valid` for clipping/rendering only; source file was not modified. The maps use source layers at their supplied present-day geometries and do not reconstruct historical plate boundaries at each earthquake origin time.\n2. A nearest mapped-boundary line is not a rupture plane, causative fault, slab surface or hypocentre-to-fault distance.\n3. PB2002 plates/orogens, Hasterok plate/subplate polygons, geological provinces and boundary-line types are distinct source concepts and must not be collapsed into one label.\n4. The event catalogue is magnitude-thresholded and does not represent all seismicity. Outside-pilot events are not controls or a tectonically inactive set.\n5. No new supporting earthquakes were queried, no sequence labels were assigned, and no final study regions were frozen.\n\n## Reproduction\nWith Python packages `pandas`, `geopandas`, `shapely`, `numpy`, `matplotlib`, run:\n\n```bash\npython scripts/build_stage1c2_gis_review_v001.py --input-dir inputs --source-dir inputs/tectonic_sources --output-dir rebuilt_output\n```\n\nThe script assumes the four analysis input CSVs are in `inputs/`; the shapefile and GeoJSON source layers are in `inputs/tectonic_sources/`.\n'''
    (out/'SOURCE_AND_METHOD_NOTES.md').write_text(notes)
    # report
    def count(code): return flag_counts.get(code,0)
    report=f'''# LAIC-GUARD Stage 1C.2.5 — GIS review and edge-case ledger v001\n\n**Status: review package only. No region has been frozen or approved.**\n\n## 1. Integrity\n\n- Frozen catalogue: **{len(c)} rows / {c.event_id.nunique()} unique IDs**.\n- Frozen catalogue SHA-256: `{sha256(cat)}`.\n- Candidate crosswalk: **{len(x)} rows / {x.event_id.nunique()} unique IDs**.\n- Catalogue-to-crosswalk shared source fields checked: **no mismatches**.\n- Event-level GIS review rows: **{len(review)}**.\n- Events carrying one or more review flags: **{int(review.gis_review_required_v001.sum())}** (flags may be low-priority source qualifiers; this is not a rejection count).\n- Long-form event-flag ledger rows: **{len(flags)}**.\n- Hasterok source features: **{len(plates)} plate/subplate polygons, {len(provinces)} geological provinces, {len(boundaries)} boundary records**.\n- PB2002 plate features: **{len(pbplates)}**.
- PB2002 orogen features: **{len(orogens)}**.\n\n## 2. Priority case counts\n\n| Review topic | Events |\n|---|---:|\n| Original geometric Himalaya/Sunda overlap | {count('MYANMAR_RECTANGLE_OVERLAP')} |\n| Persia–Tibet–Burma orogen outside all four boxes | {count('PERSIA_TIBET_BURMA_OROGEN_OUTSIDE_PILOT')} |\n| Persia–Tibet–Burma orogen inside Sunda box | {count('PERSIA_TIBET_BURMA_OROGEN_IN_SUNDA_BOX')} |\n| Bering Sea Hasterok subplate | {count('BERING_SEA_SUBPLATE')} |\n| PB2002 western Aleutians orogen | {count('WESTERN_ALEUTIANS_OROGEN')} |\n| Ryukyu Hasterok subplate | {count('RYUKYU_SUBPLATE')} |\n| PB2002 Philippines orogen | {count('PHILIPPINES_PB2002_OROGEN')} |\n| Philippine Mobile Belt candidate family | {count('PHILIPPINE_MOBILE_BELT_CANDIDATE')} |\n| New Guinea/eastern Indonesia candidate family | {count('NEW_GUINEA_EASTERN_INDONESIA_CANDIDATE')} |\n| Mariana arc candidate family | {count('MARIANA_ARC_CANDIDATE')} |\n| Sunda box events not tagged as Sunda-arc candidates | {count('SUNDA_BOX_NON_SUNDA_ARC_CANDIDATE')} |\n| Japan–Kuril box events not tagged as Kuril–Kamchatka candidates | {count('JAPAN_KURIL_BOX_NON_KURIL_CANDIDATE')} |\n| Andes box events in non-Andes/adjacent review families | {count('ANDES_BOX_NON_ANDES_REVIEW')} |\n| Himalaya–Tibet box events outside the primary collision-belt family | {count('HIMALAYA_BOX_ADJACENT_OR_UNTAGGED')} |\n| Outside-pilot events with a candidate-domain tag | {count('OUTSIDE_PILOT_WITH_CANDIDATE_DOMAIN')} |\n| Events without a pre-registered candidate family | {count('UNASSIGNED_REQUIRES_REVIEW')} |\n\nCounts are per flag and categories overlap. Do not sum them to obtain a unique-event total.\n\n## 3. Interpretation\n\n### Myanmar / Persia–Tibet–Burma\nThe seven geometric overlap events remain in `OVERLAP_REVIEW_HIMALAYA_SUNDA`. The PB2002 Persia–Tibet–Burma orogen contains {count('PERSIA_TIBET_BURMA_OROGEN_OUTSIDE_PILOT')} target events outside all original rectangles and {count('PERSIA_TIBET_BURMA_OROGEN_IN_SUNDA_BOX')} event inside the Sunda rectangle. The old rectangle edges therefore do not delimit the PB2002 orogen.\n\n### Japan–Kuril / Bering / Ryukyu\nThe Bering Sea subplate has {count('BERING_SEA_SUBPLATE')} events split across the old Japan–Kuril box and outside-pilot area; PB2002 western-Aleutians members are separately flagged. Ryukyu events are split across Japan–Kuril, Sunda and outside-pilot assignments. These units should not be pooled solely by the old boxes.\n\n### Sunda / Philippines / Molucca / New Guinea\nThe Sunda rectangle contains {count('SUNDA_BOX_NON_SUNDA_ARC_CANDIDATE')} events not tagged as the provisional Sunda-arc candidate family. PB2002's Philippines orogen has {count('PHILIPPINES_PB2002_OROGEN')} catalogue events in the Sunda rectangle; the Hasterok-based Philippine Mobile Belt family contains {count('PHILIPPINE_MOBILE_BELT_CANDIDATE')} events across the full catalogue. New Guinea/eastern Indonesia and Mariana candidates are separately flagged.\n\n### Andes and adjacent domains\nThe Andes rectangle contains {count('ANDES_BOX_NON_ANDES_REVIEW')} events tagged to broad South American, Central America/Caribbean, Nazca, Cocos or Scotia review families. These should be reviewed before the Andes region is frozen.\n\n### Unassigned/outside pilot\nThere are {count('UNASSIGNED_REQUIRES_REVIEW')} events without a pre-registered candidate family, while {count('OUTSIDE_PILOT_WITH_CANDIDATE_DOMAIN')} outside-pilot events have candidate-domain tags. The outside-pilot set is not a control group or tectonically inactive population.\n\n## 4. Map layers and symbols\n\n- Event marker colour: original pilot assignment v001.\n- Black-ring marker: event has one or more priority edge-case flags.\n- Thin gray outlines: Hasterok tectonic plate/subplate polygon outlines.\n- Pale dotted outlines: Hasterok geological-province outlines.\n- Red dashed outlines: PB2002 orogens.\n- Boundary line colours: Hasterok `type` field.\n- Black dashed rectangles: original exploratory pilot windows.\n\nThe global view skips line segments that would spuriously connect across the antimeridian. The Bering/Aleutian panel uses 0–360° longitude.\n\n## 5. Decisions not made\n\nThis package does not assign exclusive final region membership, infer causative faults, define control regions, or choose distance thresholds. The input source units are evidence layers, not validated LAIC study populations. No supporting earthquake records were downloaded; no sequence labels were assigned. Before freezing regions, the research objective must clarify whether the regional analysis concerns collision, subduction-interface, intraslab, strike-slip, or mixed tectonic settings.\n\n## 6. Files\n\n- `analysis/event_level_gis_review_v001.csv`: all 1,186 events, one row per event, plus review flags.\n- `analysis/edge_case_ledger_v001.csv`: long-form event-by-flag ledger.\n- `analysis/edge_case_flag_summary_v001.csv`: counts per flag; categories overlap.\n- `analysis/priority_edge_case_register_v001.csv`: event details for the named review topics.\n- `analysis/pilot_box_candidate_family_composition_v001.csv`: provisional family mixture for each original rectangle.\n- `maps/global_catalogue_overview_v001.png/.pdf`: global point/line overview.\n- `maps/regional_gis_review_v001.png/.pdf`: six detailed regional GIS panels.\n- `inputs/`: frozen analysis inputs and source geospatial files needed to reproduce the review.\n- `scripts/`: reproducible builder.\n\n**Decision:** retain Stage 1C.2.4 proposal v001 unchanged. Use this package for human review. It does not authorize a final region freeze or supporting-event acquisition.\n'''
    (out/'STAGE1C2_GIS_REVIEW_AND_EDGE_CASE_LEDGER_v001.md').write_text(report)
    # manifest
    rows=[]
    for f in sorted(out.rglob('*')):
        if f.is_file() and f.name!='SHA256SUMS.csv':
            rows.append({'RelativePath':f.relative_to(out).as_posix(),'SizeBytes':f.stat().st_size,'SHA256':sha256(f)})
    pd.DataFrame(rows).to_csv(out/'SHA256SUMS.csv',index=False)
    print(json.dumps(qa,indent=2))
    print('OUTPUT',out)

if __name__=='__main__': main()
