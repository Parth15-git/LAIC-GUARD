from __future__ import annotations
import argparse, hashlib, json, shutil, zipfile
from pathlib import Path
import pandas as pd

# Reproducible Stage 1C.2.4 proposal generator. It keeps PB2002 and Hasterok
# evidence independent; it never changes the original pilot_assignment_v001.

SUBPLATE_RULES = {
    'Tibet': ('INDIA_EURASIA_COLLISION_BELT_REVIEW','TIBET'),
    'Pamir': ('INDIA_EURASIA_COLLISION_BELT_REVIEW','PAMIR'),
    'Afghan': ('INDIA_EURASIA_COLLISION_BELT_REVIEW','AFGHAN'),
    'Tien Shan': ('CENTRAL_ASIA_COLLISION_REVIEW','TIEN_SHAN'),
    'Burma': ('BURMA_SHAN_THAI_COMPLEX_REVIEW','BURMA'),
    'Shan-Thai': ('BURMA_SHAN_THAI_COMPLEX_REVIEW','SHAN_THAI'),
    'Kuril-Kamchatka': ('KURIL_KAMCHATKA_ARC_REVIEW','KURIL_KAMCHATKA'),
    'Okhotsk': ('OKHOTSK_ADJACENT_DOMAIN_REVIEW','OKHOTSK'),
    'Amur': ('AMUR_ADJACENT_DOMAIN_REVIEW','AMUR'),
    'Bering Sea': ('BERING_SEA_ALEUTIAN_REVIEW','BERING_SEA'),
    'Southwest Japan Inner': ('SOUTHWEST_JAPAN_REVIEW','SOUTHWEST_JAPAN_INNER'),
    'Kinki Outer': ('SOUTHWEST_JAPAN_REVIEW','KINKI_OUTER'),
    'Izu Bonin': ('IZU_BONIN_ARC_REVIEW','IZU_BONIN'),
    'Ryukyu': ('RYUKYU_ARC_REVIEW','RYUKYU'),
    'West Sumatra': ('SUNDA_ARC_SEGMENTATION_REVIEW','WEST_SUMATRA'),
    'Sunda': ('SUNDA_ARC_SEGMENTATION_REVIEW','SUNDA_JAVA'),
    'Banda Sea': ('BANDA_TIMOR_COLLISION_REVIEW','BANDA_SEA'),
    'Timor': ('BANDA_TIMOR_COLLISION_REVIEW','TIMOR'),
    'Molucca Sea': ('MOLUCCA_DOUBLE_SUBDUCTION_REVIEW','MOLUCCA_SEA'),
    'Halmahera': ('MOLUCCA_DOUBLE_SUBDUCTION_REVIEW','HALMAHERA'),
    'Bicol': ('PHILIPPINE_MOBILE_BELT_REVIEW','BICOL'),
    'Mindanao': ('PHILIPPINE_MOBILE_BELT_REVIEW','MINDANAO'),
    'East Luzon': ('PHILIPPINE_MOBILE_BELT_REVIEW','EAST_LUZON'),
    'Philippine': ('PHILIPPINE_MOBILE_BELT_REVIEW','PHILIPPINE'),
    'West Luzon': ('PHILIPPINE_MOBILE_BELT_REVIEW','WEST_LUZON'),
    'Mamberamo': ('NEW_GUINEA_EASTERN_INDONESIA_REVIEW','MAMBERAMO'),
    'Cenderawasih': ('NEW_GUINEA_EASTERN_INDONESIA_REVIEW','CENDERAWASIH'),
    'Birds Head': ('NEW_GUINEA_EASTERN_INDONESIA_REVIEW','BIRDS_HEAD'),
    'Maoke': ('NEW_GUINEA_EASTERN_INDONESIA_REVIEW','MAOKE'),
    'Moake': ('NEW_GUINEA_EASTERN_INDONESIA_REVIEW','MOAKE_SOURCE_LABEL'),
    'North Sulawesi': ('NORTH_SULAWESI_REVIEW','NORTH_SULAWESI'),
    'Mariana': ('MARIANA_ARC_REVIEW','MARIANA'),
    'Puna': ('CENTRAL_ANDES_SEGMENTATION_REVIEW','PUNA'),
    'Altiplano': ('CENTRAL_ANDES_SEGMENTATION_REVIEW','ALTIPLANO'),
    'Peruvian': ('PERU_ANDES_REVIEW','PERUVIAN'),
    'North Andes': ('NORTHERN_ANDES_REVIEW','NORTH_ANDES'),
    'South Chile': ('SOUTHERN_ANDES_REVIEW','SOUTH_CHILE'),
    'South American': ('SOUTH_AMERICAN_PLATE_REVIEW','SOUTH_AMERICAN'),
    'Panama': ('CENTRAL_AMERICA_CARIBBEAN_REVIEW','PANAMA'),
    'Lesser Antilles': ('CENTRAL_AMERICA_CARIBBEAN_REVIEW','LESSER_ANTILLES'),
    'Coiba': ('CENTRAL_AMERICA_CARIBBEAN_REVIEW','COIBA'),
    'Cocos': ('COCOS_PLATE_REVIEW','COCOS'),
    'Nazca': ('NAZCA_PLATE_REVIEW','NAZCA'),
    'Scotia': ('SCOTIA_DOMAIN_REVIEW','SCOTIA'),
    'Indian': ('INDIAN_PLATE_ADJACENT_REVIEW','INDIAN'),
}

RATIONALE = {
'INDIA_EURASIA_COLLISION_BELT_REVIEW':'PB2002 Persia-Tibet-Burma orogen plus Hasterok Tibet/Pamir/Afghan subplates; do not collapse the subdomains.',
'CENTRAL_ASIA_COLLISION_REVIEW':'Hasterok Tien Shan subplate; adjacent tectonic domain with very low N in this catalogue.',
'BURMA_SHAN_THAI_COMPLEX_REVIEW':'Hasterok Burma/Shan-Thai subplates and PB2002 Persia-Tibet-Burma orogen; preserves all seven original overlap-review events.',
'KURIL_KAMCHATKA_ARC_REVIEW':'Hasterok Kuril-Kamchatka subplate; USGS describes the Kuril-Kamchatka arc from Hokkaido through Kurils to Kamchatka.',
'OKHOTSK_ADJACENT_DOMAIN_REVIEW':'Hasterok Okhotsk subplate; USGS identifies Pacific subduction beneath Okhotsk along the Kuril-Kamchatka arc, but this is a distinct plate-side domain.',
'AMUR_ADJACENT_DOMAIN_REVIEW':'Hasterok Amur subplate; regional GNSS literature documents an Amur-Okhotsk boundary around Hokkaido.',
'BERING_SEA_ALEUTIAN_REVIEW':'Hasterok Bering Sea subplate; separate from the Kuril-Kamchatka arc, and many events lie outside the original Japan-Kuril rectangle.',
'SOUTHWEST_JAPAN_REVIEW':'Hasterok Southwest Japan Inner and Kinki Outer units; distinct from Kuril-Kamchatka and Izu-Bonin/Ryukyu trench systems.',
'IZU_BONIN_ARC_REVIEW':'Hasterok Izu Bonin subplate; distinct intra-oceanic subduction system south of the Boso triple junction.',
'RYUKYU_ARC_REVIEW':'Hasterok Ryukyu unit; Philippine Sea plate subduction along Shikoku-Ryukyu setting. Original rectangles split these events inconsistently.',
'SUNDA_ARC_SEGMENTATION_REVIEW':'Hasterok West Sumatra and Sunda subplates; published work describes along-arc variation and different obliquity/strike-slip partitioning between Sumatra and Java.',
'BANDA_TIMOR_COLLISION_REVIEW':'Hasterok Banda Sea and Timor subplates; nearest boundaries are predominantly collision zones, unlike the Sumatra/Java margin.',
'MOLUCCA_DOUBLE_SUBDUCTION_REVIEW':'Hasterok Molucca Sea/Halmahera units; published geodynamic studies describe double-vergent or divergent double subduction.',
'PHILIPPINE_MOBILE_BELT_REVIEW':'Hasterok Bicol/Mindanao/East Luzon/Philippine/West Luzon units; PB2002 marks the Philippine Islands as an orogen, not a simple rigid plate.',
'NEW_GUINEA_EASTERN_INDONESIA_REVIEW':'Hasterok Mamberamo/Cenderawasih/Birds Head/Maoke units; separate eastern Indonesia/New Guinea candidate system.',
'NORTH_SULAWESI_REVIEW':'Hasterok North Sulawesi unit; retain independently until its relationship to Molucca and Celebes systems is reviewed.',
'MARIANA_ARC_REVIEW':'Hasterok Mariana unit; distinct western Pacific arc/back-arc domain, not part of the Sunda-Indonesia core.',
'CENTRAL_ANDES_SEGMENTATION_REVIEW':'Hasterok Puna/Altiplano units; PB2002 also marks a Puna-Sierras Pampeanas orogen. Preserve Puna and Altiplano as child units.',
'PERU_ANDES_REVIEW':'Hasterok Peruvian unit and PB2002 Peru orogen are separate evidence; the latter also includes some South American subplate events.',
'NORTHERN_ANDES_REVIEW':'Hasterok North Andes unit; Andean literature distinguishes Northern Andes from Central and Southern Andes.',
'SOUTHERN_ANDES_REVIEW':'Hasterok South Chile unit; very low N in the frozen target catalogue.',
'SOUTH_AMERICAN_PLATE_REVIEW':'Hasterok South American plate label is broad; not all events should be assumed to represent the Andean margin.',
'CENTRAL_AMERICA_CARIBBEAN_REVIEW':'Panama, Lesser Antilles and Coiba are separate from the Andean core and should not be swept into an Andes rectangle.',
'COCOS_PLATE_REVIEW':'Hasterok Cocos plate events are offshore oceanic-plate events; not Andean continental events by default.',
'NAZCA_PLATE_REVIEW':'Hasterok Nazca unit; offshore oceanic-plate events should remain distinct from South American crustal events.',
'SCOTIA_DOMAIN_REVIEW':'Hasterok Scotia unit; southern ocean tectonic setting, not Andes proper.',
'INDIAN_PLATE_ADJACENT_REVIEW':'Hasterok Indian plate label; keep independent from the Himalayan collision belt pending point-by-point review.'
}


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--package-dir',default=str(Path(__file__).resolve().parent))
    ap.add_argument('--output-dir',default='analysis')
    args=ap.parse_args()
    package=Path(args.package_dir).resolve()
    out=Path(args.output_dir).resolve()
    out.mkdir(parents=True,exist_ok=True)
    catp=package/'inputs/event_catalogue_v002.csv'
    ovp=package/'inputs/event_level_tectonic_overlay_v001.csv'
    dp=package/'inputs/event_level_tectonic_boundary_distances_v001.csv'
    for p in [catp,ovp,dp]:
        if not p.exists(): raise FileNotFoundError(p)
    cat=pd.read_csv(catp); ov=pd.read_csv(ovp); dist=pd.read_csv(dp)
    for frame,n in [(cat,'catalogue'),(ov,'overlay'),(dist,'distance')]:
        if frame.event_id.nunique()!=len(frame): raise ValueError(f'{n} has duplicate event IDs')
    if not (set(cat.event_id)==set(ov.event_id)==set(dist.event_id)):
        raise ValueError('Input event IDs do not reconcile one-to-one')
    dist_cols=['event_id','nearest_boundary_distance_km','nearest_boundary_name','nearest_boundary_type',
        'nearest_boundary_plate1','nearest_boundary_plate2','nearest_non_inferred_boundary_distance_km',
        'nearest_non_inferred_boundary_type','nearest_subduction_zone_distance_km',
        'nearest_collision_zone_distance_km','nearest_dextral_transform_distance_km',
        'nearest_sinistral_transform_distance_km','nearest_spreading_center_distance_km',
        'nearest_extension_zone_distance_km']
    d=ov.merge(dist[dist_cols],on='event_id',how='left',validate='one_to_one')
    if d.nearest_boundary_distance_km.isna().any(): raise ValueError('Missing boundary distance after join')
    d['candidate_domain_family_v001']=d.Hasterok_subplate.map(lambda v: SUBPLATE_RULES.get(v,(None,None))[0])
    d['candidate_subdomain_v001']=d.Hasterok_subplate.map(lambda v: SUBPLATE_RULES.get(v,(None,None))[1])
    d['tagging_basis_v001']=d.candidate_subdomain_v001.map(lambda x:'EXACT_HASTEROK_SUBPLATE' if pd.notna(x) else 'UNASSIGNED_SOURCE_SUBPLATE')
    d['pb2002_orogen_review_tag_v001']=d.PB2002_OROGEN_NAME
    d['pb2002_complex_orogen_flag_v001']=d.PB2002_OROGEN_NAME.notna()
    d['proposal_status_v001']='UNASSIGNED_REQUIRES_REVIEW'
    d.loc[d.candidate_subdomain_v001.notna() & d.pilot_assignment_v001.ne('OUTSIDE_PILOT'),'proposal_status_v001']='CANDIDATE_TAG_INSIDE_OR_OVERLAP_WITH_PILOT'
    d.loc[d.candidate_subdomain_v001.notna() & d.pilot_assignment_v001.eq('OUTSIDE_PILOT'),'proposal_status_v001']='ADJACENT_DOMAIN_CANDIDATE_OUTSIDE_PILOT'
    d['original_overlap_review_retained_v001']=d.pilot_assignment_v001.eq('OVERLAP_REVIEW_HIMALAYA_SUNDA')
    keep=['event_id','origin_time_utc','year_utc','target_period','latitude_deg','longitude_deg','depth_km','magnitude','magnitude_type','place',
          'pilot_assignment_v001','candidate_domain_family_v001','candidate_subdomain_v001','tagging_basis_v001','proposal_status_v001',
          'original_overlap_review_retained_v001','PB2002_PLATE_NAME','PB2002_OROGEN_NAME','pb2002_orogen_review_tag_v001',
          'pb2002_complex_orogen_flag_v001','Hasterok_plate','Hasterok_subplate','Hasterok_plate_type','Hasterok_prov_name','Hasterok_prov_type',
          'nearest_boundary_distance_km','nearest_boundary_name','nearest_boundary_type','nearest_boundary_plate1','nearest_boundary_plate2',
          'nearest_non_inferred_boundary_distance_km','nearest_non_inferred_boundary_type','nearest_subduction_zone_distance_km',
          'nearest_collision_zone_distance_km','nearest_dextral_transform_distance_km','nearest_sinistral_transform_distance_km',
          'nearest_spreading_center_distance_km','nearest_extension_zone_distance_km']
    eventout=out/'event_level_candidate_segmentation_review_v001.csv'
    d[keep].to_csv(eventout,index=False)

    # Candidate-system/child counts; tags come strictly from Hasterok subplate.
    summary=[]
    for (fam,sub),g in d[d.candidate_subdomain_v001.notna()].groupby(['candidate_domain_family_v001','candidate_subdomain_v001']):
        p=g.target_period.value_counts().to_dict()
        b=g.nearest_boundary_type.value_counts().to_dict()
        summary.append({'candidate_domain_family_v001':fam,'candidate_subdomain_v001':sub,
            'Hasterok_subplate_exact':g.Hasterok_subplate.iloc[0],'events_all_catalogue':len(g),
            'events_in_four_box_union':int(g.is_in_four_region_pilot_union.sum()),
            'events_outside_pilot':int(g.pilot_assignment_v001.eq('OUTSIDE_PILOT').sum()),
            'events_overlap_review':int(g.original_overlap_review_retained_v001.sum()),
            'events_2000_2009':int(p.get('2000_2009',0)),'events_2010_2019':int(p.get('2010_2019',0)),
            'events_2020_2025':int(p.get('2020_2025',0)),
            'median_nearest_boundary_km':round(g.nearest_boundary_distance_km.median(),3),
            'nearest_boundary_type_counts':';'.join(f'{k}:{v}' for k,v in b.items()),
            'PB2002_orogen_labels':';'.join(g.PB2002_OROGEN_NAME.dropna().value_counts().index.tolist())})
    s=pd.DataFrame(summary).sort_values(['candidate_domain_family_v001','candidate_subdomain_v001'])
    s.to_csv(out/'candidate_subdomain_summary_v001.csv',index=False)

    # Full inventory: every Hasterok subplate, including outside the candidate map.
    inventory=[]
    for sp,g in d.groupby('Hasterok_subplate',dropna=False):
        bp=g.nearest_boundary_type.value_counts().to_dict()
        inventory.append({'Hasterok_subplate':sp,'events_all_catalogue':len(g),
            'events_in_four_box_union':int(g.is_in_four_region_pilot_union.sum()),
            'events_outside_pilot':int(g.pilot_assignment_v001.eq('OUTSIDE_PILOT').sum()),
            'events_overlap_review':int(g.original_overlap_review_retained_v001.sum()),
            'candidate_domain_family_v001':g.candidate_domain_family_v001.iloc[0],
            'candidate_subdomain_v001':g.candidate_subdomain_v001.iloc[0],
            'nearest_boundary_types':';'.join(f'{k}:{v}' for k,v in bp.items()),
            'median_nearest_boundary_km':round(g.nearest_boundary_distance_km.median(),3)})
    pd.DataFrame(inventory).sort_values('events_all_catalogue',ascending=False).to_csv(out/'hasterok_subplate_inventory_v001.csv',index=False)

    # PB2002 orogens remain an independent overlay, not an alternative subplate assignment.
    oro=[]
    for name,g in d.groupby('PB2002_OROGEN_NAME',dropna=False):
        oro.append({'PB2002_OROGEN_NAME':name if pd.notna(name) else '[NO_OROGEN_MATCH]',
            'events_all_catalogue':len(g),'events_in_four_box_union':int(g.is_in_four_region_pilot_union.sum()),
            'events_outside_pilot':int(g.pilot_assignment_v001.eq('OUTSIDE_PILOT').sum()),
            'pilot_assignments':';'.join(f'{k}:{v}' for k,v in g.pilot_assignment_v001.value_counts().items()),
            'Hasterok_subplates':';'.join(f'{k}:{v}' for k,v in g.Hasterok_subplate.value_counts().items())})
    pd.DataFrame(oro).to_csv(out/'pb2002_orogen_review_inventory_v001.csv',index=False)

    pd.crosstab(d.pilot_assignment_v001,d.candidate_domain_family_v001,dropna=False).to_csv(out/'pilot_assignment_by_candidate_domain_v001.csv')
    pd.crosstab(d.pilot_assignment_v001,d.Hasterok_subplate,dropna=False).to_csv(out/'pilot_assignment_by_hasterok_subplate_v001.csv')

    meta={'catalogue_sha256':sha(catp),'overlay_sha256':sha(ovp),'distance_sha256':sha(dp),
          'catalogue_rows':len(cat),'catalogue_unique_event_ids':int(cat.event_id.nunique()),
          'overlay_rows':len(ov),'distance_rows':len(dist),'candidate_rows':len(d),'candidate_unique_event_ids':int(d.event_id.nunique()),
          'candidate_tagged_events':int(d.candidate_subdomain_v001.notna().sum()),
          'candidate_untagged_events':int(d.candidate_subdomain_v001.isna().sum()),
          'original_overlap_review_events':int(d.original_overlap_review_retained_v001.sum()),
          'outside_pilot_events_preserved':int(d.pilot_assignment_v001.eq('OUTSIDE_PILOT').sum()),
          'pb2002_orogen_matched_events':int(d.PB2002_OROGEN_NAME.notna().sum()),
          'no_network_calls':True,'no_supporting_event_records_downloaded':True,'no_sequence_labels_assigned':True}
    (out/'run_metadata_v001.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps(meta,indent=2))
    print('\nCandidate subdomain table:')
    print(s[['candidate_domain_family_v001','candidate_subdomain_v001','events_all_catalogue','events_in_four_box_union','events_outside_pilot','events_overlap_review']].to_string(index=False))

if __name__=='__main__': main()
